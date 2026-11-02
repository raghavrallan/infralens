import ComputeSection from "@/components/ComputeSection";
import { NETWORK_DEPTH } from "@/lib/network";

export default async function NetworkServicePage({ params }) {
  const { service } = await params;
  const serviceId = String(service || "");
  if (!NETWORK_DEPTH[serviceId]) {
    return <p className="text-sm text-muted">That network service is not part of this catalog.</p>;
  }
  return <ComputeSection serviceId={serviceId} />;
}
