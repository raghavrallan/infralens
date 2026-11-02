import { estateHandler } from "@/lib/estate-errors";
import { controlEstate } from "@/lib/estate-parts";

export const dynamic = "force-dynamic";

// Control only. Same payload as /api/estate/status.
export const GET = estateHandler("status", (request) => controlEstate(request));
