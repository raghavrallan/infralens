import subprocess
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.execution.validation import (
    delete_verification_confirms_absence,
    operation_hash,
    validate_operation,
)
from executors.common.runner import run_cli
from executors.common.rq_job import _preflight_found_existing, _run, _verification_succeeded
from executors.common.runner import CliResult
from app.execution.chat_actions import _resource_group_nsg_spec, _resource_group_vnet_spec
from app.execution.service import compound_result_complete


class ExecutionValidationTests(unittest.TestCase):
    def test_delete_verification_accepts_expected_not_found_result(self):
        operation = {
            "args": ["group", "delete", "--name", "testing", "--yes", "--no-wait"],
            "verify": ["group", "show", "--name", "testing", "--output", "json"],
        }
        result = SimpleNamespace(
            returncode=3,
            stdout="",
            stderr="(ResourceGroupNotFound) Resource group testing could not be found",
        )
        self.assertTrue(_verification_succeeded(operation, result))
        self.assertTrue(
            delete_verification_confirms_absence(
                operation, result.returncode, result.stdout, result.stderr
            )
        )

    def test_unrelated_verification_failures_still_fail(self):
        operation = {
            "args": ["group", "delete", "--name", "testing"],
            "verify": ["group", "show", "--name", "testing"],
        }
        result = SimpleNamespace(returncode=2, stdout="", stderr="AuthorizationFailed")
        self.assertFalse(_verification_succeeded(operation, result))

    @patch("executors.common.rq_job.run_cli")
    def test_compound_provider_steps_run_in_order(self, run):
        run.return_value = CliResult(0, "{}", "")
        operations = {
            "steps": [
                {
                    "provider": "aws",
                    "executable": "aws",
                    "args": ["ec2", "create-vpc", "--cidr-block", "10.0.0.0/16"],
                    "target": "vpc/one",
                    "preflight": ["ec2", "describe-vpcs", "--vpc-ids", "none"],
                    "verify": ["ec2", "describe-vpcs", "--vpc-ids", "one"],
                },
                {
                    "provider": "aws",
                    "executable": "aws",
                    "args": ["ec2", "create-subnet", "--vpc-id", "one", "--cidr-block", "10.0.0.0/24"],
                    "target": "subnet/one",
                    "preflight": ["ec2", "describe-subnets", "--subnet-ids", "none"],
                    "verify": ["ec2", "describe-subnets", "--subnet-ids", "one"],
                },
            ]
        }
        status, result, error = _run("aws", operations, {}, {}, lambda *_: None, lambda: False)
        self.assertEqual(status, "succeeded")
        self.assertEqual(len(result["steps"]), 2)
        self.assertEqual(run.call_count, 6)
        self.assertEqual(error, "")

    def test_compound_result_requires_every_step(self):
        operation = {"steps": [{"args": ["group", "create"]}, {"args": ["network", "nsg", "create"]}]}
        self.assertFalse(compound_result_complete(operation, {"stdout": "resource group created"}))
        self.assertTrue(compound_result_complete(operation, {"steps": [{"step": 1}, {"step": 2}]}))

    @patch("executors.common.rq_job.run_cli")
    def test_existing_parent_is_skipped_and_child_still_runs(self, run):
        run.side_effect = [
            CliResult(0, "", ""),
            CliResult(0, "", ""),  # Azure login and subscription
            CliResult(0, "true\n", ""),
            CliResult(0, "{}", ""),  # existing resource group verification
            CliResult(0, "0\n", ""),
            CliResult(0, "{}", ""),
            CliResult(0, "{}", ""),
        ]
        operation = _resource_group_nsg_spec("testing", "eastus", "test-demo-nsg", "sub-1")
        status, result, error = _run(
            "azure",
            operation,
            {"client_id": "id", "client_secret": "secret", "tenant_id": "tenant", "subscription_id": "sub-1"},
            {},
            lambda *_: None,
            lambda: False,
        )
        self.assertEqual(status, "succeeded")
        self.assertTrue(result["steps"][0]["skipped"])
        self.assertEqual(len(result["steps"]), 2)
        self.assertEqual(run.call_args_list[5].args[0][:3], ["az", "network", "nsg"])
        self.assertEqual(error, "")

        legacy_step = {key: value for key, value in operation["steps"][0].items() if key != "skip_if_exists"}
        self.assertTrue(_preflight_found_existing(legacy_step, CliResult(0, "true\n", "")))

    @patch("executors.common.rq_job.run_cli")
    def test_existing_parent_is_skipped_for_vnet_without_shell_syntax_error(self, run):
        run.side_effect = [
            CliResult(0, "", ""),  # Azure login
            CliResult(0, "", ""),  # Azure subscription
            CliResult(0, "true\n", ""),  # resource group exists
            CliResult(0, "{}", ""),  # existing resource-group verification
            CliResult(0, "\n", ""),  # VNet does not exist
            CliResult(0, "{}", ""),  # VNet create
            CliResult(0, "{}", ""),  # VNet verification
        ]
        operation = _resource_group_vnet_spec(
            "testing_eq", "eastus", "test-vnet", "10.0.0.0/16", "10.0.0.0/24", "sub-1"
        )
        status, result, error = _run(
            "azure",
            operation,
            {"client_id": "id", "client_secret": "secret", "tenant_id": "tenant", "subscription_id": "sub-1"},
            {},
            lambda *_: None,
            lambda: False,
        )
        self.assertEqual(status, "succeeded")
        self.assertTrue(result["steps"][0]["skipped"])
        self.assertEqual(result["steps"][1]["status"], "succeeded")
        self.assertEqual(error, "")

    def test_empty_vnet_preflight_list_is_allowed_to_proceed(self):
        operation = _resource_group_vnet_spec(
            "testing_eq2", "eastus", "test-vnet", "10.0.0.0/16", "10.0.0.0/24", "sub-1"
        )["steps"][1]
        self.assertFalse(
            _preflight_found_existing(operation, CliResult(0, "[]\n", ""))
        )
        self.assertFalse(
            _preflight_found_existing(operation, CliResult(0, '"[]"\n', ""))
        )

    def test_provider_executable_and_shell_syntax_are_restricted(self):
        operation = validate_operation("azure", "az", ["resource", "list", "--output", "json"], "subscription", "read_only")
        self.assertEqual(operation["executable"], "az")
        query = validate_operation(
            "azure",
            "az",
            ["network", "nsg", "list", "--query", "[?name=='test-demo-nsg'] | length(@)", "--output", "tsv"],
            "resource-group/testing",
            "read_only",
        )
        self.assertTrue(any("| length(@)" in arg for arg in query["args"]))
        punctuation = validate_operation(
            "azure",
            "az",
            ["group", "create", "--name", "testing_eq;"],
            "resource-group/testing_eq",
            "read_only",
        )
        self.assertIn("testing_eq", punctuation["args"])
        self.assertNotIn("testing_eq;", punctuation["args"])
        with self.assertRaisesRegex(ValueError, "Shell syntax"):
            validate_operation("azure", "az", ["resource", "list | cat"], "subscription", "read_only")
        with self.assertRaisesRegex(ValueError, "Credentials"):
            validate_operation("github", "gh", ["api", "--access-token", "secret"], "account", "read_only")
        with self.assertRaisesRegex(ValueError, "must use"):
            validate_operation("aws", "az", ["sts", "get-caller-identity"], "account", "read_only")

    def test_writes_require_preflight_and_verify(self):
        with self.assertRaisesRegex(ValueError, "preflight"):
            validate_operation("github", "gh", ["pr", "create"], "org/repo", "write")
        operation = validate_operation(
            "github", "gh", ["pr", "create", "--title", "Fix"], "org/repo", "write",
            ["repo", "view"], ["pr", "checks"],
        )
        self.assertEqual(len(operation["verify"]), 2)

    def test_hash_changes_when_the_approved_operation_changes(self):
        first = validate_operation("aws", "aws", ["s3api", "list-buckets"], "account", "read_only")
        second = validate_operation("aws", "aws", ["s3api", "delete-bucket", "--bucket", "x"], "account", "read_only")
        self.assertNotEqual(operation_hash(first, "read_only"), operation_hash(second, "read_only"))

    @patch("executors.common.runner.subprocess.run")
    def test_runner_never_enables_shell(self, run):
        run.return_value = subprocess.CompletedProcess(["aws", "sts"], 0, "{}", "")
        result = run_cli(["aws", "sts", "get-caller-identity"], {"PATH": ""})
        self.assertEqual(result.returncode, 0)
        self.assertFalse(run.call_args.kwargs["shell"])

    @patch("executors.common.runner.subprocess.Popen", side_effect=FileNotFoundError(2, "not found"))
    def test_runner_reports_missing_provider_cli(self, _popen):
        result = run_cli(
            ["az", "group", "show", "--name", "testing"],
            {"PATH": ""},
            cancel_check=lambda: False,
        )
        self.assertEqual(result.returncode, -1)
        self.assertIn("Provider CLI unavailable", result.stderr)
        self.assertIn("az", result.stderr)


if __name__ == "__main__":
    unittest.main()
