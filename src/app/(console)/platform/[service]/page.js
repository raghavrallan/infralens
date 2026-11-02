import ComputeSection from "@/components/ComputeSection";
import { PLATFORM_DEPTH } from "@/lib/platform";

export default async function PlatformServicePage({ params }) {
  const { service } = await params;
  const serviceId = String(service || "");
  if (!PLATFORM_DEPTH[serviceId]) {
    return <p className="text-sm text-muted">That platform service is not part of this catalog.</p>;
  }
  return <ComputeSection serviceId={serviceId} />;
}
