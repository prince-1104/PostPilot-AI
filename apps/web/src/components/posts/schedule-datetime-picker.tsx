"use client";

import { useMemo, useRef, useState, type KeyboardEvent } from "react";
import { CalendarClock, ChevronLeft, ChevronRight } from "lucide-react";
import { cn } from "cn";

import { Button } from "@/components/ui/button";
import {
  addCalendarDays,
  formatFriendlyWallLocal,
  instantToWallLocalInput,
  joinWallLocal,
  parseFlexibleWallLocal,
  splitWallLocal,
  wallLocalAtClock,
} from "@/lib/timezone";

const fieldClass =
  "w-full rounded-xl border border-input bg-background-elevated/80 px-3 py-2.5 text-sm outline-none transition-shadow focus-visible:border-violet/50 focus-visible:ring-3 focus-visible:ring-violet/30";

const segmentClass =
  "w-12 rounded-xl border border-input bg-background-elevated/80 px-2 py-2.5 text-center font-mono text-sm tabular-nums outline-none transition-shadow focus-visible:border-violet/50 focus-visible:ring-3 focus-visible:ring-violet/30";

interface Preset {
  id: string;
  label: string;
  build: (timeZone: string) => string;
}

type Meridiem = "AM" | "PM";

function to12HourParts(time24: string): { hour: string; minute: string; meridiem: Meridiem } {
  const [hRaw, mRaw] = time24.split(":");
  let hours24 = Number(hRaw);
  const minutes = Number(mRaw);
  if (Number.isNaN(hours24) || Number.isNaN(minutes)) {
    return { hour: "09", minute: "00", meridiem: "AM" };
  }
  const meridiem: Meridiem = hours24 >= 12 ? "PM" : "AM";
  hours24 = hours24 % 12;
  if (hours24 === 0) hours24 = 12;
  return {
    hour: String(hours24).padStart(2, "0"),
    minute: String(minutes).padStart(2, "0"),
    meridiem,
  };
}

function to24Hour(hour12: number, minute: number, meridiem: Meridiem): string {
  let hours24 = hour12 % 12;
  if (meridiem === "PM") hours24 += 12;
  return `${String(hours24).padStart(2, "0")}:${String(minute).padStart(2, "0")}`;
}

function buildPresets(): Preset[] {
  return [
    {
      id: "1h",
      label: "In 1 hour",
      build: (tz) => instantToWallLocalInput(new Date(Date.now() + 60 * 60_000).toISOString(), tz),
    },
    {
      id: "3h",
      label: "In 3 hours",
      build: (tz) =>
        instantToWallLocalInput(new Date(Date.now() + 3 * 60 * 60_000).toISOString(), tz),
    },
    {
      id: "tonight",
      label: "Tonight 7 PM",
      build: (tz) => {
        const today = instantToWallLocalInput(new Date().toISOString(), tz).slice(0, 10);
        const candidate = wallLocalAtClock(today, 19, 0);
        const nowWall = instantToWallLocalInput(new Date().toISOString(), tz);
        if (candidate <= nowWall) {
          return wallLocalAtClock(addCalendarDays(today, 1), 19, 0);
        }
        return candidate;
      },
    },
    {
      id: "tomorrow-am",
      label: "Tomorrow 9 AM",
      build: (tz) => {
        const today = instantToWallLocalInput(new Date().toISOString(), tz).slice(0, 10);
        return wallLocalAtClock(addCalendarDays(today, 1), 9, 0);
      },
    },
    {
      id: "tomorrow-pm",
      label: "Tomorrow 6 PM",
      build: (tz) => {
        const today = instantToWallLocalInput(new Date().toISOString(), tz).slice(0, 10);
        return wallLocalAtClock(addCalendarDays(today, 1), 18, 0);
      },
    },
    {
      id: "monday",
      label: "Next Mon 9 AM",
      build: (tz) => {
        const today = instantToWallLocalInput(new Date().toISOString(), tz).slice(0, 10);
        const weekdayName = new Intl.DateTimeFormat("en-US", {
          timeZone: tz,
          weekday: "short",
        }).format(new Date());
        const map: Record<string, number> = {
          Sun: 0,
          Mon: 1,
          Tue: 2,
          Wed: 3,
          Thu: 4,
          Fri: 5,
          Sat: 6,
        };
        const current = map[weekdayName] ?? 0;
        const daysUntil = ((1 - current + 7) % 7) || 7;
        return wallLocalAtClock(addCalendarDays(today, daysUntil), 9, 0);
      },
    },
  ];
}

interface ScheduleDateTimePickerProps {
  value: string;
  timeZone: string;
  onChange: (next: string) => void;
  disabled?: boolean;
  id?: string;
}

export function ScheduleDateTimePicker({
  value,
  timeZone,
  onChange,
  disabled = false,
  id = "schedule-when",
}: ScheduleDateTimePickerProps) {
  const { date, time } = splitWallLocal(value);
  const presets = useMemo(() => buildPresets(), []);
  const clock = to12HourParts(time || "09:00");
  const [draft, setDraft] = useState<string | null>(null);
  const [typedError, setTypedError] = useState<string | null>(null);
  const [hourDraft, setHourDraft] = useState<string | null>(null);
  const [minuteDraft, setMinuteDraft] = useState<string | null>(null);
  const minuteRef = useRef<HTMLInputElement>(null);
  const hourRef = useRef<HTMLInputElement>(null);
  const meridiemRef = useRef<HTMLSelectElement>(null);
  const hourDigitsRef = useRef("");
  const minuteDigitsRef = useRef("");
  const typed = draft ?? formatFriendlyWallLocal(value);
  const hourDisplay = hourDraft ?? clock.hour;
  const minuteDisplay = minuteDraft ?? clock.minute;

  function applyValue(next: string) {
    setDraft(null);
    setTypedError(null);
    setHourDraft(null);
    setMinuteDraft(null);
    hourDigitsRef.current = "";
    minuteDigitsRef.current = "";
    onChange(next);
  }

  function ensureDate(): string {
    return date || instantToWallLocalInput(new Date().toISOString(), timeZone).slice(0, 10);
  }

  function commitClock(nextHour: string, nextMinute: string, nextMeridiem: Meridiem) {
    const hourNum = Number(nextHour);
    const minuteNum = Number(nextMinute);
    if (
      Number.isNaN(hourNum) ||
      Number.isNaN(minuteNum) ||
      hourNum < 1 ||
      hourNum > 12 ||
      minuteNum < 0 ||
      minuteNum > 59
    ) {
      return false;
    }
    const paddedHour = String(hourNum).padStart(2, "0");
    const paddedMinute = String(minuteNum).padStart(2, "0");
    setDraft(null);
    setTypedError(null);
    setHourDraft(paddedHour);
    setMinuteDraft(paddedMinute);
    hourDigitsRef.current = paddedHour;
    minuteDigitsRef.current = paddedMinute;
    onChange(joinWallLocal(ensureDate(), to24Hour(hourNum, minuteNum, nextMeridiem)));
    return true;
  }

  function setDate(nextDate: string) {
    const nextTime =
      time ||
      instantToWallLocalInput(new Date().toISOString(), timeZone).slice(11, 16) ||
      "09:00";
    applyValue(joinWallLocal(nextDate, nextTime));
  }

  function nudgeDay(delta: number) {
    if (!date) return;
    setDate(addCalendarDays(date, delta));
  }

  function nudgeMinutes(delta: number) {
    if (!value) return;
    const [d, t] = value.split("T");
    if (!d || !t) return;
    const [hRaw, mRaw] = t.split(":");
    const hours = Number(hRaw);
    const minutes = Number(mRaw);
    if (Number.isNaN(hours) || Number.isNaN(minutes)) return;
    const absolute = hours * 60 + minutes + delta;
    const dayDelta = Math.floor(absolute / (24 * 60));
    const wrapped = ((absolute % (24 * 60)) + 24 * 60) % (24 * 60);
    const rh = Math.floor(wrapped / 60);
    const rm = wrapped % 60;
    applyValue(
      joinWallLocal(
        addCalendarDays(d, dayDelta),
        `${String(rh).padStart(2, "0")}:${String(rm).padStart(2, "0")}`,
      ),
    );
  }

  function currentMinuteForCommit(): string {
    if (minuteDigitsRef.current.length > 0) return minuteDigitsRef.current.padStart(2, "0");
    if (minuteDraft && minuteDraft.length > 0) return minuteDraft.padStart(2, "0");
    return clock.minute;
  }

  function currentHourForCommit(): string {
    if (hourDigitsRef.current.length > 0) return hourDigitsRef.current.padStart(2, "0");
    if (hourDraft && hourDraft.length > 0) return hourDraft.padStart(2, "0");
    return clock.hour;
  }

  function onHourKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key >= "0" && event.key <= "9") {
      event.preventDefault();
      let next = hourDigitsRef.current + event.key;
      if (next.length > 2) next = next.slice(-2);
      const asNum = Number(next);
      // 13–19 are invalid hours: keep the last digit as a fresh start.
      if (next.length === 2 && asNum > 12) {
        next = event.key;
      }
      hourDigitsRef.current = next;
      setHourDraft(next);
      if (next.length === 2) {
        const hourNum = Number(next);
        if (hourNum >= 1 && hourNum <= 12) {
          commitClock(next, currentMinuteForCommit(), clock.meridiem);
          window.setTimeout(() => {
            minuteDigitsRef.current = "";
            setMinuteDraft("");
            minuteRef.current?.focus();
          }, 0);
        }
      }
      return;
    }
    if (event.key === "Backspace") {
      event.preventDefault();
      const next = hourDigitsRef.current.slice(0, -1);
      hourDigitsRef.current = next;
      setHourDraft(next);
      return;
    }
    if (event.key === "ArrowRight" || event.key === "Enter") {
      event.preventDefault();
      minuteRef.current?.focus();
    }
  }

  function onMinuteKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key >= "0" && event.key <= "9") {
      event.preventDefault();
      let next = minuteDigitsRef.current + event.key;
      if (next.length > 2) next = next.slice(-2);
      const asNum = Number(next);
      if (next.length === 2 && asNum > 59) {
        next = event.key;
      }
      minuteDigitsRef.current = next;
      setMinuteDraft(next);
      if (next.length === 2) {
        const minuteNum = Number(next);
        if (minuteNum >= 0 && minuteNum <= 59) {
          commitClock(currentHourForCommit(), next, clock.meridiem);
          window.setTimeout(() => meridiemRef.current?.focus(), 0);
        }
      }
      return;
    }
    if (event.key === "Backspace") {
      event.preventDefault();
      if (minuteDigitsRef.current.length === 0) {
        hourRef.current?.focus();
        return;
      }
      const next = minuteDigitsRef.current.slice(0, -1);
      minuteDigitsRef.current = next;
      setMinuteDraft(next);
      return;
    }
    if (event.key === "ArrowLeft") {
      event.preventDefault();
      hourRef.current?.focus();
    }
  }

  function onHourFocus() {
    hourDigitsRef.current = "";
    setHourDraft("");
  }

  function onMinuteFocus() {
    minuteDigitsRef.current = "";
    setMinuteDraft("");
  }

  function onHourBlur() {
    if (hourDraft === null) return;
    if (hourDraft === "") {
      setHourDraft(null);
      hourDigitsRef.current = "";
      return;
    }
    const hourNum = Number(hourDraft);
    if (hourNum >= 1 && hourNum <= 12) {
      commitClock(String(hourNum).padStart(2, "0"), currentMinuteForCommit(), clock.meridiem);
    } else {
      setHourDraft(null);
      hourDigitsRef.current = "";
    }
  }

  function onMinuteBlur() {
    if (minuteDraft === null) return;
    if (minuteDraft === "") {
      setMinuteDraft(null);
      minuteDigitsRef.current = "";
      return;
    }
    const minuteNum = Number(minuteDraft);
    if (minuteNum >= 0 && minuteNum <= 59) {
      commitClock(currentHourForCommit(), String(minuteNum).padStart(2, "0"), clock.meridiem);
    } else {
      setMinuteDraft(null);
      minuteDigitsRef.current = "";
    }
  }

  function commitTyped() {
    const parsed = parseFlexibleWallLocal(typed, timeZone);
    if (!parsed) {
      setTypedError("Could not read that. Try 21-11-2026 3:07 PM or 2026-11-21 15:07");
      return;
    }
    applyValue(parsed);
  }

  function onTypedKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key === "Enter") {
      event.preventDefault();
      commitTyped();
    }
    if (event.key === "Escape") {
      setDraft(null);
      setTypedError(null);
    }
  }

  const activePresetId = presets.find((preset) => preset.build(timeZone) === value)?.id ?? null;

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap gap-1.5" role="group" aria-label="Quick schedule times">
        {presets.map((preset) => {
          const active = activePresetId === preset.id;
          return (
            <Button
              key={preset.id}
              type="button"
              size="sm"
              variant={active ? "default" : "outline"}
              disabled={disabled}
              className={cn(
                "h-7 rounded-full px-2.5 text-xs",
                active
                  ? "gradient-primary border-0 text-white"
                  : "border-border/80 bg-surface/40 text-muted-foreground hover:text-foreground",
              )}
              onClick={() => applyValue(preset.build(timeZone))}
            >
              {preset.label}
            </Button>
          );
        })}
      </div>

      <div className="flex flex-col gap-2">
        <label htmlFor={`${id}-typed`} className="text-sm font-medium">
          Type date &amp; time
        </label>
        <input
          id={`${id}-typed`}
          type="text"
          inputMode="text"
          autoComplete="off"
          spellCheck={false}
          className={cn(fieldClass, "font-mono text-[0.8125rem]", typedError && "border-rose/50")}
          value={typed}
          disabled={disabled}
          placeholder="e.g. 21-11-2026 3:07 PM"
          aria-invalid={typedError ? true : undefined}
          aria-describedby={`${id}-typed-help`}
          onChange={(event) => {
            setDraft(event.target.value);
            setTypedError(null);
          }}
          onBlur={() => {
            if (draft !== null) commitTyped();
          }}
          onKeyDown={onTypedKeyDown}
        />
        <p id={`${id}-typed-help`} className="text-xs text-muted-foreground">
          Type freely, then press Enter. Accepts{" "}
          <span className="font-meta">21-11-2026 3:07 PM</span>,{" "}
          <span className="font-meta">2026-11-21 15:07</span>,{" "}
          <span className="font-meta">Nov 21 2026 3pm</span>
        </p>
        {typedError ? (
          <p className="text-xs text-rose" role="alert">
            {typedError}
          </p>
        ) : null}
      </div>

      <div className="grid gap-3 sm:grid-cols-2">
        <div className="flex flex-col gap-2">
          <label htmlFor={`${id}-date`} className="text-sm font-medium">
            Date
          </label>
          <div className="flex items-center gap-1.5">
            <Button
              type="button"
              size="icon-sm"
              variant="outline"
              className="shrink-0 bg-surface/40"
              disabled={disabled || !date}
              aria-label="Previous day"
              onClick={() => nudgeDay(-1)}
            >
              <ChevronLeft className="size-4" />
            </Button>
            <input
              id={`${id}-date`}
              type="date"
              className={fieldClass}
              value={date}
              required
              disabled={disabled}
              onChange={(event) => setDate(event.target.value)}
            />
            <Button
              type="button"
              size="icon-sm"
              variant="outline"
              className="shrink-0 bg-surface/40"
              disabled={disabled || !date}
              aria-label="Next day"
              onClick={() => nudgeDay(1)}
            >
              <ChevronRight className="size-4" />
            </Button>
          </div>
        </div>

        <div className="flex flex-col gap-2">
          <p className="text-sm font-medium" id={`${id}-time-label`}>
            Time
          </p>
          <div className="flex items-center gap-1.5" role="group" aria-labelledby={`${id}-time-label`}>
            <Button
              type="button"
              size="icon-sm"
              variant="outline"
              className="shrink-0 bg-surface/40"
              disabled={disabled || !value}
              aria-label="15 minutes earlier"
              onClick={() => nudgeMinutes(-15)}
            >
              −15
            </Button>

            <div className="flex min-w-0 flex-1 items-center gap-1">
              <input
                ref={hourRef}
                id={`${id}-hour`}
                type="text"
                inputMode="numeric"
                autoComplete="off"
                spellCheck={false}
                maxLength={2}
                disabled={disabled}
                className={segmentClass}
                value={hourDisplay}
                aria-label="Hour"
                placeholder="HH"
                onFocus={onHourFocus}
                onBlur={onHourBlur}
                onChange={() => {
                  /* Digits handled in onKeyDown so two-digit values like 10 work reliably. */
                }}
                onKeyDown={onHourKeyDown}
              />
              <span className="font-mono text-sm text-muted-foreground" aria-hidden>
                :
              </span>
              <input
                ref={minuteRef}
                id={`${id}-minute`}
                type="text"
                inputMode="numeric"
                autoComplete="off"
                spellCheck={false}
                maxLength={2}
                disabled={disabled}
                className={segmentClass}
                value={minuteDisplay}
                aria-label="Minute"
                placeholder="MM"
                onFocus={onMinuteFocus}
                onBlur={onMinuteBlur}
                onChange={() => {
                  /* Digits handled in onKeyDown so two-digit values like 46 work reliably. */
                }}
                onKeyDown={onMinuteKeyDown}
              />
              <select
                ref={meridiemRef}
                id={`${id}-meridiem`}
                className={cn(fieldClass, "w-[4.5rem] shrink-0 px-2")}
                value={clock.meridiem}
                disabled={disabled}
                aria-label="AM or PM"
                onChange={(event) => {
                  const next = event.target.value === "PM" ? "PM" : "AM";
                  commitClock(currentHourForCommit(), currentMinuteForCommit(), next);
                }}
              >
                <option value="AM">AM</option>
                <option value="PM">PM</option>
              </select>
            </div>

            <Button
              type="button"
              size="icon-sm"
              variant="outline"
              className="shrink-0 bg-surface/40"
              disabled={disabled || !value}
              aria-label="15 minutes later"
              onClick={() => nudgeMinutes(15)}
            >
              +15
            </Button>
          </div>
        </div>
      </div>

      <p className="flex items-center gap-2 text-xs text-muted-foreground">
        <CalendarClock className="size-3.5 shrink-0 text-electric-blue" aria-hidden />
        Wall-clock in <span className="font-meta text-foreground/80">{timeZone}</span>
        {" · "}
        type HH then MM jumps automatically
      </p>
    </div>
  );
}
