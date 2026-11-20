/**
 * Convert a wall-clock datetime-local value in an IANA zone to an offset-aware ISO string.
 *
 * The API rejects naive datetimes and requires the offset to match the zone at that instant.
 */

const FALLBACK_TIMEZONES = [
  "UTC",
  "America/New_York",
  "America/Chicago",
  "America/Denver",
  "America/Los_Angeles",
  "America/Sao_Paulo",
  "Europe/London",
  "Europe/Paris",
  "Europe/Berlin",
  "Asia/Kolkata",
  "Asia/Dubai",
  "Asia/Singapore",
  "Asia/Tokyo",
  "Australia/Sydney",
] as const;

export function listIanaTimezones(): string[] {
  try {
    if (typeof Intl !== "undefined" && "supportedValuesOf" in Intl) {
      const supported = (
        Intl as unknown as { supportedValuesOf: (key: string) => string[] }
      ).supportedValuesOf("timeZone");
      if (Array.isArray(supported) && supported.length > 0) {
        return supported;
      }
    }
  } catch {
    // Fall through to curated list.
  }
  return [...FALLBACK_TIMEZONES];
}

export function guessBrowserTimezone(): string {
  try {
    const detected = Intl.DateTimeFormat().resolvedOptions().timeZone;
    if (typeof detected === "string" && detected.length > 0) {
      return detected;
    }
  } catch {
    // ignore
  }
  return "UTC";
}

function pad(value: number, width = 2): string {
  return String(value).padStart(width, "0");
}

function formatOffset(totalMinutes: number): string {
  const sign = totalMinutes >= 0 ? "+" : "-";
  const abs = Math.abs(totalMinutes);
  const hours = Math.floor(abs / 60);
  const minutes = abs % 60;
  return `${sign}${pad(hours)}:${pad(minutes)}`;
}

/** Offset of `timeZone` at `instant`, in minutes east of UTC. */
function zoneOffsetMinutes(instant: Date, timeZone: string): number {
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone,
    timeZoneName: "shortOffset",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).formatToParts(instant);

  const tzName = parts.find((part) => part.type === "timeZoneName")?.value ?? "GMT";
  if (tzName === "UTC" || tzName === "GMT") {
    return 0;
  }
  const match = tzName.match(/GMT([+-])(\d{1,2})(?::?(\d{2}))?/i);
  if (!match) {
    // Fallback: compare wall time in zone vs UTC components.
    const wall = Object.fromEntries(
      new Intl.DateTimeFormat("en-US", {
        timeZone,
        hour12: false,
        year: "numeric",
        month: "2-digit",
        day: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
      })
        .formatToParts(instant)
        .filter((part) => part.type !== "literal")
        .map((part) => [part.type, part.value]),
    );
    const asUtc = Date.UTC(
      Number(wall.year),
      Number(wall.month) - 1,
      Number(wall.day),
      Number(wall.hour) % 24,
      Number(wall.minute),
      Number(wall.second),
    );
    return Math.round((asUtc - instant.getTime()) / 60000);
  }
  const sign = match[1] === "-" ? -1 : 1;
  const hours = Number(match[2]);
  const minutes = Number(match[3] ?? "0");
  return sign * (hours * 60 + minutes);
}

/**
 * Interpret `YYYY-MM-DDTHH:mm` (or with seconds) as wall time in `timeZone`
 * and return an ISO-8601 string with the correct numeric offset.
 */
export function wallTimeToOffsetAwareIso(localDateTime: string, timeZone: string): string {
  const match = localDateTime.match(
    /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})(?::(\d{2}))?$/,
  );
  if (!match) {
    throw new Error("Use a local date and time in YYYY-MM-DDTHH:mm form.");
  }
  const year = Number(match[1]);
  const month = Number(match[2]);
  const day = Number(match[3]);
  const hour = Number(match[4]);
  const minute = Number(match[5]);
  const second = Number(match[6] ?? "0");

  // First guess: treat wall time as UTC, then correct by the zone offset.
  let utcMs = Date.UTC(year, month - 1, day, hour, minute, second);
  let offset = zoneOffsetMinutes(new Date(utcMs), timeZone);
  utcMs = Date.UTC(year, month - 1, day, hour, minute, second) - offset * 60_000;

  // Second pass handles DST transitions where the offset changes.
  const offset2 = zoneOffsetMinutes(new Date(utcMs), timeZone);
  if (offset2 !== offset) {
    utcMs = Date.UTC(year, month - 1, day, hour, minute, second) - offset2 * 60_000;
    offset = offset2;
  }

  const instant = new Date(utcMs);
  const finalOffset = zoneOffsetMinutes(instant, timeZone);
  const localMs = utcMs + finalOffset * 60_000;
  const local = new Date(localMs);

  return (
    `${local.getUTCFullYear()}-${pad(local.getUTCMonth() + 1)}-${pad(local.getUTCDate())}` +
    `T${pad(local.getUTCHours())}:${pad(local.getUTCMinutes())}:${pad(local.getUTCSeconds())}` +
    formatOffset(finalOffset)
  );
}

/** Format an instant for a datetime-local input in the given IANA zone. */
export function instantToWallLocalInput(iso: string, timeZone: string): string {
  const instant = new Date(iso);
  if (Number.isNaN(instant.getTime())) {
    return "";
  }
  const parts = Object.fromEntries(
    new Intl.DateTimeFormat("en-CA", {
      timeZone,
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      hour12: false,
    })
      .formatToParts(instant)
      .filter((part) => part.type !== "literal")
      .map((part) => [part.type, part.value]),
  );
  const hour = parts.hour === "24" ? "00" : parts.hour;
  return `${parts.year}-${parts.month}-${parts.day}T${hour}:${parts.minute}`;
}

export function formatInTimezone(iso: string, timeZone: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "Unknown";
  return new Intl.DateTimeFormat(undefined, {
    timeZone,
    dateStyle: "medium",
    timeStyle: "short",
  }).format(date);
}

/** Default datetime-local value: now + lead minutes in the given zone. */
export function defaultLocalDateTime(timeZone: string, leadMinutes = 30): string {
  const when = new Date(Date.now() + leadMinutes * 60_000);
  return instantToWallLocalInput(when.toISOString(), timeZone);
}
