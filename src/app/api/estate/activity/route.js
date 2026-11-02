import { estateHandler } from "@/lib/estate-errors";
import { estatePart } from "@/lib/estate-parts";

export const dynamic = "force-dynamic";

export const GET = estateHandler("activity", (request) => estatePart(request, "activity"));
