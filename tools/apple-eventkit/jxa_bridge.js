ObjC.import("Foundation");

function fail(message) {
  const err = JSON.stringify({ ok: false, error: message, backend: "jxa" }, null, 2);
  $.NSFileHandle.fileHandleWithStandardError.writeData(
    $.NSString.stringWithString(err + "\n").dataUsingEncoding($.NSUTF8StringEncoding)
  );
  $.exit(1);
}

function pad2(n) {
  return String(n).padStart(2, "0");
}

function formatISO(date) {
  if (!date || date === null || date === undefined) return null;
  const d = date instanceof Date ? date : new Date(date);
  if (isNaN(d.getTime())) return null;
  const tzMin = -d.getTimezoneOffset();
  const sign = tzMin >= 0 ? "+" : "-";
  const absMin = Math.abs(tzMin);
  const tzH = pad2(Math.floor(absMin / 60));
  const tzM = pad2(absMin % 60);
  return (
    d.getFullYear() +
    "-" +
    pad2(d.getMonth() + 1) +
    "-" +
    pad2(d.getDate()) +
    "T" +
    pad2(d.getHours()) +
    ":" +
    pad2(d.getMinutes()) +
    ":" +
    pad2(d.getSeconds()) +
    sign +
    tzH +
    ":" +
    tzM
  );
}

function isDateOnly(raw) {
  return /^\d{4}-\d{2}-\d{2}$/.test(String(raw).trim());
}

function parseAlertOffsets(raw) {
  const trimmed = String(raw).trim();
  if (!trimmed) return [];
  const lower = trimmed.toLowerCase();
  if (lower === "none" || lower === "off") return [];
  const out = [];
  for (const part of trimmed.split(",")) {
    const token = part.trim().toLowerCase();
    if (!token || token === "none" || token === "off") continue;
    if (token === "9am" || token === "09:00") {
      out.push(540);
      continue;
    }
    const cleaned = token.endsWith("m") ? token.slice(0, -1) : token;
    const mins = Number(cleaned);
    if (!Number.isInteger(mins)) {
      fail("Invalid --alert '" + raw + "'. Use integer minutes (e.g. -30, -15,0, 540), '9am', or 'none'.");
    }
    out.push(mins);
  }
  return out;
}

function defaultCalendarAlertOffsets(allDay, location) {
  if (allDay) return [540];
  if (location && String(location).trim() !== "") return [];
  return [-30];
}

function parseDate(raw) {
  const s = String(raw).trim();
  // Date-only: YYYY-MM-DD -> local 00:00:00
  const dateOnly = /^(\d{4})-(\d{2})-(\d{2})$/.exec(s);
  if (dateOnly) {
    return new Date(Number(dateOnly[1]), Number(dateOnly[2]) - 1, Number(dateOnly[3]), 0, 0, 0, 0);
  }
  // Local datetime without tz: YYYY-MM-DD[T ]HH:MM(:SS)?
  const localDT = /^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})(?::(\d{2}))?$/.exec(s);
  if (localDT) {
    return new Date(
      Number(localDT[1]),
      Number(localDT[2]) - 1,
      Number(localDT[3]),
      Number(localDT[4]),
      Number(localDT[5]),
      Number(localDT[6] || "0"),
      0
    );
  }
  const d = new Date(s);
  if (isNaN(d.getTime())) {
    fail("Invalid date '" + raw + "'. Expected ISO-8601 (e.g. 2026-11-16T16:30:00+08:00, 2026-11-16 16:30, or 2026-11-16).");
  }
  return d;
}

function parseBool(raw) {
  const s = String(raw).toLowerCase();
  if (s === "true" || s === "1" || s === "yes") return true;
  if (s === "false" || s === "0" || s === "no") return false;
  fail("Invalid boolean '" + raw + "'. Expected true or false.");
}

function parsePriority(raw) {
  const s = String(raw).toLowerCase();
  if (s === "none" || s === "0") return 0;
  if (s === "high" || s === "1") return 1;
  if (s === "medium" || s === "5") return 5;
  if (s === "low" || s === "9") return 9;
  const n = Number(raw);
  if (Number.isInteger(n) && n >= 0 && n <= 9) return n;
  fail("Invalid priority '" + raw + "'. Use 0/none, 1/high, 5/medium, 9/low.");
}

function safeProp(fn, fallback = null) {
  try {
    const v = fn();
    return v === undefined ? fallback : v;
  } catch (e) {
    return fallback;
  }
}

function resolveCalendar(calApp, nameOrId) {
  const cals = calApp.calendars();
  for (const c of cals) {
    if (safeProp(() => c.name()) === nameOrId) return c;
  }
  const lower = nameOrId.toLowerCase();
  for (const c of cals) {
    const n = safeProp(() => c.name(), "");
    if (n.toLowerCase() === lower) return c;
  }
  fail("Could not find calendar matching '" + nameOrId + "'.");
}

function defaultCalendar(calApp) {
  const cals = calApp.calendars();
  for (const c of cals) {
    if (safeProp(() => c.writable(), false)) return c;
  }
  if (cals.length > 0) return cals[0];
  fail("No calendars available.");
}

function serializeEvent(ev, calName) {
  const alerts = [];
  try {
    for (const a of ev.displayAlarms()) {
      const v = safeProp(() => a.triggerInterval(), null);
      if (v !== null) alerts.push(v);
    }
  } catch (e) {}
  try {
    for (const a of ev.soundAlarms()) {
      const v = safeProp(() => a.triggerInterval(), null);
      if (v !== null && !alerts.includes(v)) alerts.push(v);
    }
  } catch (e) {}
  return {
    id: safeProp(() => ev.uid(), ""),
    title: safeProp(() => ev.summary(), ""),
    calendar: calName,
    start: formatISO(safeProp(() => ev.startDate(), null)),
    end: formatISO(safeProp(() => ev.endDate(), null)),
    allDay: Boolean(safeProp(() => ev.alldayEvent(), false)),
    location: safeProp(() => ev.location(), null),
    notes: safeProp(() => ev.description(), null),
    url: safeProp(() => ev.url(), null),
    alerts: alerts,
  };
}

function findEventById(calApp, id) {
  const cals = calApp.calendars();
  for (const c of cals) {
    if (!safeProp(() => c.writable(), false)) continue;
    try {
      const matches = c.events.whose({ uid: id })();
      if (matches && matches.length > 0) {
        return { event: matches[0], calendar: c };
      }
    } catch (e) {
      // Some read-only / subscription calendars throw on whose()
    }
  }
  fail("Event not found for id '" + id + "'.");
}

function resolveReminderList(remApp, nameOrId) {
  const lists = remApp.lists();
  for (const l of lists) {
    if (safeProp(() => l.id()) === nameOrId || safeProp(() => l.name()) === nameOrId) return l;
  }
  const lower = nameOrId.toLowerCase();
  for (const l of lists) {
    if (safeProp(() => l.name(), "").toLowerCase() === lower) return l;
  }
  fail("Could not find reminder list matching '" + nameOrId + "'.");
}

function serializeReminder(rem, listName, listId) {
  const rmd = formatISO(safeProp(() => rem.remindMeDate(), null));
  return {
    id: safeProp(() => rem.id(), ""),
    title: safeProp(() => rem.name(), ""),
    list: listName || safeProp(() => rem.container().name(), ""),
    listId: listId || safeProp(() => rem.container().id(), ""),
    completed: Boolean(safeProp(() => rem.completed(), false)),
    completionDate: formatISO(safeProp(() => rem.completionDate(), null)),
    dueDate: formatISO(safeProp(() => rem.dueDate(), null)),
    alarms: rmd ? [rmd] : [],
    priority: safeProp(() => rem.priority(), 0),
    notes: safeProp(() => rem.body(), null),
  };
}

function findReminderById(remApp, id) {
  try {
    const r = remApp.reminders.byId(id);
    // Touch name() to verify it exists
    const _ = r.name();
    return r;
  } catch (e) {
    fail("Reminder not found for id '" + id + "'.");
  }
}

function handleCal(sub, options, flags) {
  const calApp = Application("Calendar");
  if (sub === "lists") {
    const cals = calApp.calendars().map((c) => ({
      title: safeProp(() => c.name(), ""),
      writable: Boolean(safeProp(() => c.writable(), false)),
      description: safeProp(() => c.description(), null),
    }));
    return { ok: true, backend: "jxa", calendars: cals };
  }

  if (sub === "events") {
    const now = new Date();
    const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate(), 0, 0, 0, 0);
    const fromDate = options.from ? parseDate(options.from) : startOfToday;
    let toDate;
    if (options.to) {
      toDate = parseDate(options.to);
    } else {
      const days = options.days ? Number(options.days) : 7;
      toDate = new Date(fromDate.getTime() + days * 86400 * 1000);
    }
    const SKIP_NOISY_CALS = new Set([
      "Scheduled Reminders",
      "Siri Suggestions",
      "US Holidays",
      "中国大陆节假日",
      "Birthdays",
    ]);
    const includeAll = flags.includes("all-calendars");
    const targetCals = options.calendar
      ? [resolveCalendar(calApp, options.calendar)]
      : calApp.calendars().filter((c) => includeAll || !SKIP_NOISY_CALS.has(safeProp(() => c.name(), "")));
    const q = options.query ? options.query.toLowerCase() : null;
    const out = [];
    for (const c of targetCals) {
      const calName = safeProp(() => c.name(), "");
      try {
        const evs = c.events.whose({
          _and: [
            { startDate: { _greaterThanEquals: fromDate } },
            { startDate: { _lessThanEquals: toDate } },
          ],
        })();
        for (const ev of evs) {
          const item = serializeEvent(ev, calName);
          if (q) {
            const hay = ((item.title || "") + " " + (item.location || "") + " " + (item.notes || "")).toLowerCase();
            if (!hay.includes(q)) continue;
          }
          out.push(item);
        }
      } catch (e) {
        // Ignore calendars that do not support whose()
      }
    }
    out.sort((a, b) => (a.start || "").localeCompare(b.start || ""));
    return {
      ok: true,
      backend: "jxa",
      from: formatISO(fromDate),
      to: formatISO(toDate),
      count: out.length,
      events: out,
    };
  }

function applyCalendarAlerts(calApp, ev, alertOpt, isNewEvent, allDay, location) {
  let offsets;
  if (alertOpt !== undefined) {
    offsets = parseAlertOffsets(alertOpt);
  } else if (isNewEvent) {
    offsets = defaultCalendarAlertOffsets(allDay, location);
  } else {
    return;
  }
  let existingCount = 0;
  try {
    existingCount = ev.displayAlarms().length;
  } catch (e) {}
  if (offsets.length < existingCount) {
    fail("Calendar JXA backend cannot remove existing alarms (grant Calendar Full Access for EventKit backend to clear/reduce alarms).");
  }
  for (let i = 0; i < offsets.length; i++) {
    if (i < existingCount) {
      ev.displayAlarms[i].triggerInterval = offsets[i];
    } else {
      ev.displayAlarms.push(calApp.DisplayAlarm({ triggerInterval: offsets[i] }));
    }
  }
}

  if (sub === "add") {
    if (!options.title) fail("Missing required --title");
    if (!options.start) fail("Missing required --start");
    const parsedStart = parseDate(options.start);
    const allDay = flags.includes("all-day");
    const startDate = allDay
      ? new Date(parsedStart.getFullYear(), parsedStart.getMonth(), parsedStart.getDate(), 0, 0, 0, 0)
      : parsedStart;
    let endDate;
    if (options.end) {
      endDate = parseDate(options.end);
    } else if (options.duration) {
      endDate = new Date(startDate.getTime() + Number(options.duration) * 60 * 1000);
    } else if (allDay) {
      endDate = new Date(startDate.getFullYear(), startDate.getMonth(), startDate.getDate(), 23, 59, 59, 0);
    } else {
      endDate = new Date(startDate.getTime() + 3600 * 1000);
    }
    const cal = options.calendar ? resolveCalendar(calApp, options.calendar) : defaultCalendar(calApp);
    const props = {
      summary: options.title,
      startDate: startDate,
      endDate: endDate,
      alldayEvent: allDay,
    };
    if (options.location !== undefined) props.location = options.location;
    if (options.notes !== undefined) props.description = options.notes;
    if (options.url !== undefined) props.url = options.url;

    const ev = calApp.Event(props);
    cal.events.push(ev);
    applyCalendarAlerts(calApp, ev, options.alert, true, allDay, options.location);
    const calName = safeProp(() => cal.name(), "");
    return { ok: true, backend: "jxa", event: serializeEvent(ev, calName) };
  }

  if (sub === "update") {
    if (!options.id) fail("Missing required --id");
    const found = findEventById(calApp, options.id);
    const ev = found.event;
    if (options.title !== undefined) ev.summary = options.title;
    if (options.start !== undefined) ev.startDate = parseDate(options.start);
    if (options.end !== undefined) ev.endDate = parseDate(options.end);
    if (options.location !== undefined) ev.location = options.location;
    if (options.notes !== undefined) ev.description = options.notes;
    if (options.url !== undefined) ev.url = options.url;
    applyCalendarAlerts(
      calApp,
      ev,
      options.alert,
      false,
      Boolean(safeProp(() => ev.alldayEvent(), false)),
      safeProp(() => ev.location(), null)
    );
    const calName = safeProp(() => found.calendar.name(), "");
    return { ok: true, backend: "jxa", event: serializeEvent(ev, calName) };
  }

  if (sub === "delete") {
    if (!options.id) fail("Missing required --id");
    const found = findEventById(calApp, options.id);
    calApp.delete(found.event);
    return { ok: true, backend: "jxa", deleted: true, id: options.id };
  }

  fail("Unknown 'cal' subcommand '" + sub + "'.");
}

function handleRem(sub, options, flags) {
  const remApp = Application("Reminders");
  if (sub === "lists") {
    const lists = remApp.lists().map((l) => ({
      id: safeProp(() => l.id(), ""),
      title: safeProp(() => l.name(), ""),
    }));
    return { ok: true, backend: "jxa", lists: lists };
  }

  if (sub === "list") {
    const targetLists = options.list ? [resolveReminderList(remApp, options.list)] : remApp.lists();
    const compFilter = (options.completed || "false").toLowerCase();
    if (!["true", "false", "all"].includes(compFilter)) {
      fail("Invalid --completed '" + compFilter + "'. Use true, false, or all.");
    }
    const cutoff = options["due-before"] ? parseDate(options["due-before"]) : null;
    const q = options.query ? options.query.toLowerCase() : null;
    const out = [];

    for (const l of targetLists) {
      const listName = safeProp(() => l.name(), "");
      const listId = safeProp(() => l.id(), "");
      let rems;
      if (compFilter === "false") {
        rems = l.reminders.whose({ completed: false })();
      } else if (compFilter === "true") {
        rems = l.reminders.whose({ completed: true })();
      } else {
        rems = l.reminders();
      }
      for (const r of rems) {
        if (cutoff) {
          const dd = safeProp(() => r.dueDate(), null);
          if (!dd || dd > cutoff) continue;
        }
        const item = serializeReminder(r, listName, listId);
        if (q) {
          const hay = ((item.title || "") + " " + (item.notes || "")).toLowerCase();
          if (!hay.includes(q)) continue;
        }
        out.push(item);
      }
    }
    return { ok: true, backend: "jxa", count: out.length, reminders: out };
  }

  if (sub === "add") {
    if (!options.title) fail("Missing required --title");
    const list = options.list ? resolveReminderList(remApp, options.list) : remApp.defaultList();
    const props = { name: options.title };
    if (options.due !== undefined) {
      const dueDate = parseDate(options.due);
      if (isDateOnly(options.due)) {
        props.alldayDueDate = dueDate;
      } else {
        props.dueDate = dueDate;
        if (!flags.includes("no-alarm")) {
          props.remindMeDate = dueDate;
        }
      }
    }
    if (options.priority !== undefined) props.priority = parsePriority(options.priority);
    if (options.notes !== undefined) props.body = options.notes;
    const rem = remApp.Reminder(props);
    list.reminders.push(rem);
    return {
      ok: true,
      backend: "jxa",
      reminder: serializeReminder(rem, safeProp(() => list.name(), ""), safeProp(() => list.id(), "")),
    };
  }

  if (sub === "update") {
    if (!options.id) fail("Missing required --id");
    let rem = findReminderById(remApp, options.id);
    if (options.title !== undefined) rem.name = options.title;
    if (flags.includes("clear-due")) {
      rem.dueDate = null;
      rem.alldayDueDate = null;
      rem.remindMeDate = null;
    } else if (options.due !== undefined) {
      const dueDate = parseDate(options.due);
      if (isDateOnly(options.due)) {
        rem.remindMeDate = null;
        rem.alldayDueDate = dueDate;
      } else {
        rem.dueDate = dueDate;
        rem.remindMeDate = flags.includes("no-alarm") ? null : dueDate;
      }
    } else if (flags.includes("no-alarm")) {
      rem.remindMeDate = null;
    }
    if (options.priority !== undefined) rem.priority = parsePriority(options.priority);
    if (options.notes !== undefined) rem.body = options.notes;
    if (options.completed !== undefined) rem.completed = parseBool(options.completed);
    if (options.list !== undefined) {
      const targetList = resolveReminderList(remApp, options.list);
      remApp.move(rem, { to: targetList });
    }
    return { ok: true, backend: "jxa", reminder: serializeReminder(rem, null, null) };
  }

  if (sub === "complete") {
    if (!options.id) fail("Missing required --id");
    const rem = findReminderById(remApp, options.id);
    rem.completed = !flags.includes("undo");
    return { ok: true, backend: "jxa", reminder: serializeReminder(rem, null, null) };
  }

  if (sub === "delete") {
    if (!options.id) fail("Missing required --id");
    const rem = findReminderById(remApp, options.id);
    remApp.delete(rem);
    return { ok: true, backend: "jxa", deleted: true, id: options.id };
  }

  fail("Unknown 'rem' subcommand '" + sub + "'.");
}

function run(argv) {
  if (!argv || argv.length === 0) fail("Missing JSON payload argument.");
  const req = JSON.parse(argv[0]);
  const cmd = req.cmd;
  const sub = req.sub;
  const options = req.options || {};
  const flags = req.flags || [];

  let result;
  if (cmd === "cal") {
    result = handleCal(sub, options, flags);
  } else if (cmd === "rem") {
    result = handleRem(sub, options, flags);
  } else {
    fail("Unsupported JXA command '" + cmd + "'.");
  }
  return JSON.stringify(result, null, 2);
}
