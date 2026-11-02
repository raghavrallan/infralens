import ComputeSection from "@/components/ComputeSection";
import { COMPUTE_DEPTH } from "@/lib/compute";

export default async function ComputeServicePage({ params }) {
  const { service } = await params;
  const serviceId = String(service || "");
  if (!COMPUTE_DEPTH[serviceId]) {
    return <p className="text-sm text-muted">That compute service is not part of this catalog.</p>;
  }
  return <ComputeSection serviceId={serviceId} />;
}
