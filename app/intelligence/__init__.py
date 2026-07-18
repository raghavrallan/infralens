"""DevOps Intelligence Layer.

A second execution module on top of the skills suite: a Risk Engine that gates
actions by action-class x blast-radius, a Redis/RQ-backed workflow engine that
runs the read-only diagnose skills unattended, and the findings they produce for
the dashboard.
"""
