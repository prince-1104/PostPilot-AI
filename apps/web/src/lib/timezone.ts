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

/** Default datetime-local value: now + lead minutes in the given zone, rounded up to 15 minutes. */
export function defaultLocalDateTime(timeZone: string, leadMinutes = 30): string {
  const when = new Date(Date.now() + leadMinutes * 60_000);
  const wall = instantToWallLocalInput(when.toISOString(), timeZone);
  const { date, time } = splitWallLocal(wall);
  if (!date || !time) return wall;
  const [hRaw, mRaw] = time.split(":");
  const total = Number(hRaw) * 60 + Number(mRaw);
  if (Number.isNaN(total)) return wall;
  const rounded = Math.ceil(total / 15) * 15;
  if (rounded >= 24 * 60) {
    return wallLocalAtClock(addCalendarDays(date, 1), 0, 0);
  }
  return wallLocalAtClock(date, Math.floor(rounded / 60), rounded % 60);
}

/** Split `YYYY-MM-DDTHH:mm` into date + HH:mm parts. */
export function splitWallLocal(value: string): { date: string; time: string } {
  if (!value || !value.includes("T")) return { date: "", time: "" };
  const [date, rest = ""] = value.split("T");
  const time = rest.slice(0, 5);
  return { date: date ?? "", time };
}

/** Join calendar date + HH:mm into a datetime-local wall string. */
export function joinWallLocal(date: string, time: string): string {
  if (!date || !time) return "";
  return `${date}T${time.slice(0, 5)}`;
}

/** Add (or subtract) whole calendar days to a `YYYY-MM-DD` string. */
export function addCalendarDays(date: string, days: number): string {
  const [yRaw, mRaw, dRaw] = date.split("-");
  const year = Number(yRaw);
  const month = Number(mRaw);
  const day = Number(dRaw);
  if (!year || !month || !day) return date;
  const utc = new Date(Date.UTC(year, month - 1, day + days));
  return `${utc.getUTCFullYear()}-${pad(utc.getUTCMonth() + 1)}-${pad(utc.getUTCDate())}`;
}

/** Build `YYYY-MM-DDTHH:mm` from a calendar date and clock time. */
export function wallLocalAtClock(date: string, hour: number, minute: number): string {
  return joinWallLocal(date, `${pad(hour)}:${pad(minute)}`);
}

/** Friendly display for a wall-local value, e.g. `21-11-2026 3:07 PM`. */
export function formatFriendlyWallLocal(value: string): string {
  const { date, time } = splitWallLocal(value);
  if (!date || !time) return "";
  const [y, m, d] = date.split("-");
  const [hRaw, mRaw] = time.split(":");
  const hours24 = Number(hRaw);
  const minutes = Number(mRaw);
  if (!y || !m || !d || Number.isNaN(hours24) || Number.isNaN(minutes)) return value;
  const period = hours24 >= 12 ? "PM" : "AM";
  const hours12 = hours24 % 12 === 0 ? 12 : hours24 % 12;
  return `${d}-${m}-${y} ${hours12}:${pad(minutes)} ${period}`;
}

/**
 * Parse common typed date/time strings into `YYYY-MM-DDTHH:mm`.
 * Supports:
 * - 2026-11-21 15:07 / 2026-11-21T15:07
 * - 21-11-2026 3:07 PM / 21/11/2026 3:07pm
 * - Nov 21 2026 3pm / November 21, 2026 15:07
 * Relative words use `timeZone` for "today" context when only a time is given.
 */
export function parseFlexibleWallLocal(raw: string, timeZone: string): string | null {
  const input = raw.trim().replace(/\s+/g, " ");
  if (!input) return null;

  // Already wall-local
  if (/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}/.test(input)) {
    return input.slice(0, 16);
  }

  // ISO-ish with space: 2026-11-21 15:07
  const isoSpace = input.match(/^(\d{4})-(\d{2})-(\d{2})[ T](\d{1,2}):(\d{2})(?::\d{2})?\s*(am|pm)?$/i);
  if (isoSpace) {
    const hour = applyAmPm(Number(isoSpace[4]), isoSpace[6] ?? null);
    if (hour == null) return null;
    return wallLocalAtClock(
      `${isoSpace[1]}-${isoSpace[2]}-${isoSpace[3]}`,
      hour,
      Number(isoSpace[5]),
    );
  }

  // DMY: 21-11-2026 3:07 PM  or 21/11/2026 15:07
  const dmy = input.match(
    /^(\d{1,2})[/.-](\d{1,2})[/.-](\d{4})\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)?$/i,
  );
  if (dmy) {
    const day = Number(dmy[1]);
    const month = Number(dmy[2]);
    const year = Number(dmy[3]);
    const hour = applyAmPm(Number(dmy[4]), dmy[6] ?? null);
    const minute = Number(dmy[5] ?? "0");
    if (hour == null || !validYmd(year, month, day) || minute > 59) return null;
    return wallLocalAtClock(`${year}-${pad(month)}-${pad(day)}`, hour, minute);
  }

  // Month name: Nov 21 2026 3:07 PM / November 21, 2026 3pm
  const named = input.match(
    /^([A-Za-z]{3,9})\s+(\d{1,2}),?\s+(\d{4})\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)?$/i,
  );
  if (named) {
    const month = monthFromName(named[1] ?? "");
    const day = Number(named[2]);
    const year = Number(named[3]);
    const hour = applyAmPm(Number(named[4]), named[6] ?? null);
    const minute = Number(named[5] ?? "0");
    if (month == null || hour == null || !validYmd(year, month, day) || minute > 59) return null;
    return wallLocalAtClock(`${year}-${pad(month)}-${pad(day)}`, hour, minute);
  }

  // Time only: 3:07 PM / 15:07 — use today's date in zone
  const timeOnly = input.match(/^(\d{1,2})(?::(\d{2}))?\s*(am|pm)?$/i);
  if (timeOnly) {
    const hour = applyAmPm(Number(timeOnly[1]), timeOnly[3] ?? null);
    const minute = Number(timeOnly[2] ?? "0");
    if (hour == null || minute > 59) return null;
    const today = instantToWallLocalInput(new Date().toISOString(), timeZone).slice(0, 10);
    return wallLocalAtClock(today, hour, minute);
  }

  return null;
}

function applyAmPm(hour: number, meridiem: string | null): number | null {
  if (Number.isNaN(hour) || hour < 0 || hour > 23) return null;
  if (!meridiem) {
    if (hour > 23) return null;
    return hour;
  }
  const tag = meridiem.toLowerCase();
  if (hour < 1 || hour > 12) return null;
  if (tag === "am") return hour === 12 ? 0 : hour;
  return hour === 12 ? 12 : hour + 12;
}

function validYmd(year: number, month: number, day: number): boolean {
  if (month < 1 || month > 12 || day < 1 || day > 31) return false;
  const dt = new Date(Date.UTC(year, month - 1, day));
  return (
    dt.getUTCFullYear() === year && dt.getUTCMonth() === month - 1 && dt.getUTCDate() === day
  );
}

function monthFromName(name: string): number | null {
  const key = name.slice(0, 3).toLowerCase();
  const months: Record<string, number> = {
    jan: 1,
    feb: 2,
    mar: 3,
    apr: 4,
    may: 5,
    jun: 6,
    jul: 7,
    aug: 8,
    sep: 9,
    oct: 10,
    nov: 11,
    dec: 12,
  };
  return months[key] ?? null;
}
