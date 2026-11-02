import { estateHandler } from "@/lib/estate-errors";
import { controlEstate } from "@/lib/estate-parts";

export const dynamic = "force-dynamic";

export const GET = estateHandler("status", (request) => controlEstate(request));
