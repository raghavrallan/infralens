import ComputeSection from "@/components/ComputeSection";
import { DATA_DEPTH } from "@/lib/data";

export default async function DataServicePage({ params }) {
  const { service } = await params;
  const serviceId = String(service || "");
  if (!DATA_DEPTH[serviceId]) {
    return <p className="text-sm text-muted">That data service is not part of this catalog.</p>;
  }
  return <ComputeSection serviceId={serviceId} />;
}
