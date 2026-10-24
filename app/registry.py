from dataclasses import dataclass
import logging

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RegistryLookupResult:
    status: str
    plate_text: str
    vehicle: dict[str, str] | None = None
    owner_details: dict[str, str] | None = None


class VehicleRegistryAdapter:
    """Permission boundary for an approved vehicle-registry integration."""

    def lookup(self, plate_text: str, actor: str, authorized: bool) -> RegistryLookupResult:
        logger.info(
            "vehicle_registry_lookup actor=%s plate=%s authorized=%s status=unavailable",
            actor,
            plate_text,
            authorized,
        )
        if not authorized:
            return RegistryLookupResult("forbidden", plate_text)
        return RegistryLookupResult("unavailable", plate_text)
