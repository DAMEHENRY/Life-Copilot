import CoreLocation
import EventKit
import Foundation

// MARK: - CLI Error & Output Helpers

struct CLIError: Error, CustomStringConvertible {
    let message: String
    var description: String { message }
}

func printJSON(_ value: Any) {
    do {
        let data = try JSONSerialization.data(
            withJSONObject: value,
            options: [.prettyPrinted, .sortedKeys, .withoutEscapingSlashes]
        )
        if let str = String(data: data, encoding: .utf8) {
            print(str)
        }
    } catch {
        fail("Failed to serialize JSON: \(error.localizedDescription)")
    }
}

func fail(_ message: String, code: Int32 = 1) -> Never {
    let payload: [String: Any] = ["ok": false, "error": message]
    if let data = try? JSONSerialization.data(
        withJSONObject: payload,
        options: [.prettyPrinted, .sortedKeys, .withoutEscapingSlashes]
    ), let str = String(data: data, encoding: .utf8) {
        FileHandle.standardError.write(Data((str + "\n").utf8))
    } else {
        FileHandle.standardError.write(Data(("Error: \(message)\n").utf8))
    }
    exit(code)
}

// MARK: - Date Formatting & Parsing

enum DateHelper {
    static let isoFormatter: ISO8601DateFormatter = {
        let f = ISO8601DateFormatter()
        f.timeZone = TimeZone.current
        f.formatOptions = [.withInternetDateTime]
        return f
    }()

    static let isoFractionalFormatter: ISO8601DateFormatter = {
        let f = ISO8601DateFormatter()
        f.timeZone = TimeZone.current
        f.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        return f
    }()

    static func format(_ date: Date?) -> Any {
        guard let date = date else { return NSNull() }
        return isoFormatter.string(from: date)
    }

    static func parse(_ raw: String) throws -> Date {
        let s = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        if let d = isoFractionalFormatter.date(from: s) ?? isoFormatter.date(from: s) {
            return d
        }
        let formats = [
            "yyyy-MM-dd'T'HH:mm:ss",
            "yyyy-MM-dd'T'HH:mm",
            "yyyy-MM-dd HH:mm:ss",
            "yyyy-MM-dd HH:mm",
            "yyyy-MM-dd",
        ]
        for fmt in formats {
            let df = DateFormatter()
            df.locale = Locale(identifier: "en_US_POSIX")
            df.timeZone = TimeZone.current
            df.dateFormat = fmt
            if let d = df.date(from: s) {
                return d
            }
        }
        throw CLIError(
            message: "Invalid date '\(raw)'. Expected ISO-8601 (e.g. 2026-11-16T16:30:00+08:00, 2026-11-16 16:30, or 2026-11-16)."
        )
    }
}

// MARK: - Authorization Helpers

func statusString(_ status: EKAuthorizationStatus) -> String {
    switch status {
    case .notDetermined: return "notDetermined"
    case .restricted: return "restricted"
    case .denied: return "denied"
    case .fullAccess: return "fullAccess"
    case .writeOnly: return "writeOnly"
    @unknown default: return "unknown"
    }
}

func waitFor(_ body: (@escaping @Sendable (Bool, Error?) -> Void) -> Void) throws -> Bool {
    final class Box: @unchecked Sendable {
        var done = false
        var granted = false
        var error: Error?
    }
    let box = Box()
    body { ok, err in
        box.granted = ok
        box.error = err
        box.done = true
    }
    while !box.done {
        RunLoop.current.run(mode: .default, before: Date(timeIntervalSinceNow: 0.05))
    }
    if let err = box.error {
        throw err
    }
    return box.granted
}

func hasCalendarFullAccess(_ store: EKEventStore) -> Bool {
    let st = EKEventStore.authorizationStatus(for: .event)
    if st == .fullAccess { return true }
    if st == .notDetermined {
        return (try? waitFor { store.requestFullAccessToEvents(completion: $0) }) ?? false
    }
    return false
}

func hasReminderFullAccess(_ store: EKEventStore) -> Bool {
    let st = EKEventStore.authorizationStatus(for: .reminder)
    if st == .fullAccess { return true }
    if st == .notDetermined {
        return (try? waitFor { store.requestFullAccessToReminders(completion: $0) }) ?? false
    }
    return false
}

func runJXACapture(
    cmd: String,
    sub: String,
    options: [String: String],
    flags: [String],
    timeoutSec: TimeInterval = 15
) throws -> (exitCode: Int32, stdout: Data, stderr: Data) {
    let execURL = URL(fileURLWithPath: CommandLine.arguments[0]).resolvingSymlinksInPath()
    let bridgeURL = execURL.deletingLastPathComponent().appendingPathComponent("jxa_bridge.js")
    guard FileManager.default.fileExists(atPath: bridgeURL.path) else {
        throw CLIError(message: "EventKit permission unavailable and JXA fallback not found at \(bridgeURL.path).")
    }

    let payload: [String: Any] = [
        "cmd": cmd,
        "sub": sub,
        "options": options,
        "flags": flags,
    ]
    guard let data = try? JSONSerialization.data(withJSONObject: payload, options: []),
          let jsonStr = String(data: data, encoding: .utf8) else {
        throw CLIError(message: "Failed to encode JXA request payload.")
    }

    let proc = Process()
    proc.executableURL = URL(fileURLWithPath: "/usr/bin/osascript")
    proc.arguments = ["-l", "JavaScript", bridgeURL.path, jsonStr]
    let outPipe = Pipe()
    let errPipe = Pipe()
    proc.standardOutput = outPipe
    proc.standardError = errPipe
    try proc.run()

    let deadline = Date(timeIntervalSinceNow: timeoutSec)
    while proc.isRunning && Date() < deadline {
        Thread.sleep(forTimeInterval: 0.05)
    }
    if proc.isRunning {
        proc.terminate()
        throw CLIError(message: "JXA bridge timed out after \(Int(timeoutSec))s for '\(cmd) \(sub)'.")
    }
    let outData = outPipe.fileHandleForReading.readDataToEndOfFile()
    let errData = errPipe.fileHandleForReading.readDataToEndOfFile()
    return (proc.terminationStatus, outData, errData)
}

func runJXAFallback(cmd: String, sub: String, parsed: ParsedArgs, refreshAfter: Bool = false, store: EKEventStore) -> Never {
    do {
        let res = try runJXACapture(
            cmd: cmd,
            sub: sub,
            options: parsed.options,
            flags: Array(parsed.flags),
            timeoutSec: 20
        )
        if !res.stdout.isEmpty {
            FileHandle.standardOutput.write(res.stdout)
        }
        if !res.stderr.isEmpty {
            FileHandle.standardError.write(res.stderr)
        }
        if res.exitCode == 0 && refreshAfter {
            _ = try? generateSnapshot(store, days: 30, outURL: defaultSnapshotURL(), maxAgeSec: nil, bestEffort: true)
        }
        exit(res.exitCode)
    } catch {
        fail(String(describing: error))
    }
}

// MARK: - Argument Parser

struct ParsedArgs {
    var positionals: [String] = []
    var options: [String: String] = [:]
    var flags: Set<String> = []
}

func parseArgs(_ args: [String]) throws -> ParsedArgs {
    var result = ParsedArgs()
    var i = 0
    while i < args.count {
        let arg = args[i]
        if arg.hasPrefix("--") {
            let key = String(arg.dropFirst(2))
            if let eqIdx = key.firstIndex(of: "=") {
                let name = String(key[..<eqIdx])
                let val = String(key[key.index(after: eqIdx)...])
                result.options[name] = val
            } else {
                let booleanFlags: Set<String> = ["all-day", "undo", "clear-due", "help", "best-effort", "all-calendars"]
                if booleanFlags.contains(key) {
                    result.flags.insert(key)
                } else {
                    guard i + 1 < args.count else {
                        throw CLIError(message: "Missing value for --\(key)")
                    }
                    result.options[key] = args[i + 1]
                    i += 1
                }
            }
        } else if arg == "-h" {
            result.flags.insert("help")
        } else {
            result.positionals.append(arg)
        }
        i += 1
    }
    return result
}

func parseBool(_ raw: String) throws -> Bool {
    switch raw.lowercased() {
    case "true", "1", "yes": return true
    case "false", "0", "no": return false
    default: throw CLIError(message: "Invalid boolean '\(raw)'. Expected true or false.")
    }
}

func parsePriority(_ raw: String) throws -> Int {
    switch raw.lowercased() {
    case "none", "0": return 0
    case "high", "1": return 1
    case "medium", "5": return 5
    case "low", "9": return 9
    default:
        if let n = Int(raw), (0...9).contains(n) { return n }
        throw CLIError(message: "Invalid priority '\(raw)'. Use 0/none, 1/high, 5/medium, 9/low.")
    }
}

func parseSpan(_ raw: String?) throws -> EKSpan {
    guard let raw = raw else { return .thisEvent }
    switch raw.lowercased() {
    case "this": return .thisEvent
    case "future": return .futureEvents
    default: throw CLIError(message: "Invalid --span '\(raw)'. Use 'this' or 'future'.")
    }
}

// MARK: - Serialization

func serializeCalendar(_ cal: EKCalendar) -> [String: Any] {
    let typeStr: String
    switch cal.type {
    case .local: typeStr = "local"
    case .calDAV: typeStr = "calDAV"
    case .exchange: typeStr = "exchange"
    case .subscription: typeStr = "subscription"
    case .birthday: typeStr = "birthday"
    @unknown default: typeStr = "unknown"
    }
    return [
        "id": cal.calendarIdentifier,
        "title": cal.title,
        "source": cal.source?.title ?? "",
        "type": typeStr,
        "allowsContentModifications": cal.allowsContentModifications,
    ]
}

func serializeEvent(_ ev: EKEvent) -> [String: Any] {
    [
        "id": ev.eventIdentifier ?? "",
        "title": ev.title ?? "",
        "calendar": ev.calendar?.title ?? "",
        "calendarId": ev.calendar?.calendarIdentifier ?? "",
        "start": DateHelper.format(ev.startDate),
        "end": DateHelper.format(ev.endDate),
        "allDay": ev.isAllDay,
        "location": ev.location ?? NSNull(),
        "notes": ev.notes ?? NSNull(),
        "url": ev.url?.absoluteString ?? NSNull(),
        "hasRecurrenceRules": ev.hasRecurrenceRules,
        "isDetached": ev.isDetached,
    ]
}

func serializeLocationAlarm(_ alarms: [EKAlarm]?) -> Any {
    guard let alarm = alarms?.first(where: { $0.structuredLocation != nil }),
          let loc = alarm.structuredLocation else {
        return NSNull()
    }
    let prox: String
    switch alarm.proximity {
    case .enter: prox = "enter"
    case .leave: prox = "leave"
    case .none: prox = "none"
    @unknown default: prox = "unknown"
    }
    var dict: [String: Any] = [
        "title": loc.title ?? "",
        "proximity": prox,
        "radius": loc.radius,
    ]
    if let geo = loc.geoLocation {
        dict["lat"] = geo.coordinate.latitude
        dict["lon"] = geo.coordinate.longitude
    }
    return dict
}

func buildStructuredLocation(options: [String: String]) throws -> EKStructuredLocation? {
    let title = options["location"]
    let latRaw = options["lat"]
    let lonRaw = options["lon"]
    if title == nil && latRaw == nil && lonRaw == nil {
        return nil
    }
    let loc = EKStructuredLocation(title: title ?? "Pinned Location")
    if (latRaw != nil) != (lonRaw != nil) {
        throw CLIError(message: "Both --lat and --lon must be provided together.")
    }
    if let latS = latRaw, let lonS = lonRaw {
        guard let lat = Double(latS), let lon = Double(lonS) else {
            throw CLIError(message: "Invalid --lat or --lon coordinates.")
        }
        loc.geoLocation = CLLocation(latitude: lat, longitude: lon)
    }
    if let radS = options["radius"] {
        guard let rad = Double(radS), rad > 0 else {
            throw CLIError(message: "Invalid --radius '\(radS)'. Must be positive meters.")
        }
        loc.radius = rad
    } else if loc.geoLocation != nil {
        loc.radius = 100
    }
    return loc
}

func parseProximity(_ raw: String?) throws -> EKAlarmProximity {
    guard let raw = raw else { return .enter }
    switch raw.lowercased() {
    case "enter", "arrive": return .enter
    case "leave", "depart": return .leave
    case "none": return .none
    default: throw CLIError(message: "Invalid --proximity '\(raw)'. Use enter or leave.")
    }
}

func serializeReminder(_ rem: EKReminder) -> [String: Any] {
    let cal = Calendar.current
    let due: Date? = rem.dueDateComponents.flatMap { cal.date(from: $0) }
    return [
        "id": rem.calendarItemIdentifier,
        "title": rem.title ?? "",
        "list": rem.calendar?.title ?? "",
        "listId": rem.calendar?.calendarIdentifier ?? "",
        "completed": rem.isCompleted,
        "completionDate": DateHelper.format(rem.completionDate),
        "dueDate": DateHelper.format(due),
        "priority": rem.priority,
        "notes": rem.notes ?? NSNull(),
        "url": rem.url?.absoluteString ?? NSNull(),
        "locationAlarm": serializeLocationAlarm(rem.alarms),
    ]
}

func resolveCalendar(_ store: EKEventStore, titleOrId: String, entityType: EKEntityType) throws -> EKCalendar {
    let cals = store.calendars(for: entityType)
    if let match = cals.first(where: { $0.calendarIdentifier == titleOrId }) {
        return match
    }
    if let match = cals.first(where: { $0.title == titleOrId }) {
        return match
    }
    if let match = cals.first(where: { $0.title.caseInsensitiveCompare(titleOrId) == .orderedSame }) {
        return match
    }
    let kind = entityType == .event ? "calendar" : "reminder list"
    throw CLIError(message: "Could not find \(kind) matching '\(titleOrId)'.")
}

func fetchReminders(_ store: EKEventStore, calendars: [EKCalendar]?) throws -> [EKReminder] {
    let pred = store.predicateForReminders(in: calendars)
    final class Box: @unchecked Sendable {
        var done = false
        var items: [EKReminder] = []
    }
    let box = Box()
    store.fetchReminders(matching: pred) { rems in
        box.items = rems ?? []
        box.done = true
    }
    while !box.done {
        RunLoop.current.run(mode: .default, before: Date(timeIntervalSinceNow: 0.05))
    }
    return box.items
}

func findReminder(_ store: EKEventStore, id: String) throws -> EKReminder {
    if let item = store.calendarItem(withIdentifier: id) as? EKReminder {
        return item
    }
    let all = try fetchReminders(store, calendars: nil)
    if let match = all.first(where: { $0.calendarItemIdentifier == id }) {
        return match
    }
    throw CLIError(message: "Reminder not found for id '\(id)'.")
}

// MARK: - Places Catalog

struct PlaceEntry: Codable {
    let key: String
    let location: String
    let aliases: [String]?
    let lat: Double?
    let lon: Double?
    let radius: Double?
}

struct PlacesFile: Codable {
    let places: [PlaceEntry]
}

func placesFileURL() -> URL {
    let execURL = URL(fileURLWithPath: CommandLine.arguments[0]).resolvingSymlinksInPath()
    return execURL.deletingLastPathComponent().appendingPathComponent("places.json")
}

func loadPlaces() -> [PlaceEntry] {
    let url = placesFileURL()
    guard let data = try? Data(contentsOf: url),
          let decoded = try? JSONDecoder().decode(PlacesFile.self, from: data) else {
        return []
    }
    return decoded.places
}

func findPlace(_ query: String, in places: [PlaceEntry]) -> PlaceEntry? {
    let q = query.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
    if q.isEmpty { return nil }
    if let m = places.first(where: { $0.key.lowercased() == q }) { return m }
    if let m = places.first(where: { $0.location.lowercased() == q }) { return m }
    if let m = places.first(where: { ($0.aliases ?? []).contains(where: { $0.lowercased() == q }) }) { return m }
    return nil
}

func resolvePlaceOptions(_ parsed: inout ParsedArgs) throws {
    let places = loadPlaces()
    if let placeRef = parsed.options["place"] {
        guard let hit = findPlace(placeRef, in: places) else {
            throw CLIError(message: "Unknown --place '\(placeRef)'. Run 'eventkit-ctl places' to list configured places.")
        }
        if parsed.options["location"] == nil { parsed.options["location"] = hit.location }
        if parsed.options["lat"] == nil, let lat = hit.lat { parsed.options["lat"] = String(lat) }
        if parsed.options["lon"] == nil, let lon = hit.lon { parsed.options["lon"] = String(lon) }
        if parsed.options["radius"] == nil, let rad = hit.radius { parsed.options["radius"] = String(rad) }
    } else if let locRef = parsed.options["location"], let hit = findPlace(locRef, in: places) {
        parsed.options["location"] = hit.location
        if parsed.options["lat"] == nil, let lat = hit.lat { parsed.options["lat"] = String(lat) }
        if parsed.options["lon"] == nil, let lon = hit.lon { parsed.options["lon"] = String(lon) }
        if parsed.options["radius"] == nil, let rad = hit.radius { parsed.options["radius"] = String(rad) }
    }
}

func handlePlaces() {
    let places = loadPlaces()
    let rows: [[String: Any]] = places.map { p in
        var d: [String: Any] = [
            "key": p.key,
            "location": p.location,
            "aliases": p.aliases ?? [],
        ]
        if let lat = p.lat { d["lat"] = lat }
        if let lon = p.lon { d["lon"] = lon }
        if let rad = p.radius { d["radius"] = rad }
        return d
    }
    printJSON([
        "ok": true,
        "count": rows.count,
        "file": placesFileURL().path,
        "places": rows,
    ])
}

// MARK: - Schedule Snapshot

func defaultSnapshotURL() -> URL {
    let execURL = URL(fileURLWithPath: CommandLine.arguments[0]).resolvingSymlinksInPath()
    return execURL.deletingLastPathComponent().appendingPathComponent("schedule-snapshot.json")
}

func snapshotStampURL() -> URL {
    URL(fileURLWithPath: NSTemporaryDirectory()).appendingPathComponent("life-eventkit-snapshot.stamp")
}

func canonicalJSON(_ value: Any) -> Data? {
    try? JSONSerialization.data(withJSONObject: value, options: [.sortedKeys, .withoutEscapingSlashes])
}

func fetchEventsForSnapshot(_ store: EKEventStore, days: Int) throws -> (from: String, to: String, events: [[String: Any]]) {
    let now = Date()
    let startOfToday = Calendar.current.startOfDay(for: now)
    let toDate = Calendar.current.date(byAdding: .day, value: days, to: startOfToday)
        ?? startOfToday.addingTimeInterval(TimeInterval(days * 86400))
    let fromStr = DateHelper.isoFormatter.string(from: startOfToday)
    let toStr = DateHelper.isoFormatter.string(from: toDate)

    if hasCalendarFullAccess(store) {
        let pred = store.predicateForEvents(withStart: startOfToday, end: toDate, calendars: nil)
        let events = store.events(matching: pred).sorted { $0.startDate < $1.startDate }.map(serializeEvent)
        return (fromStr, toStr, events)
    }

    let res = try runJXACapture(
        cmd: "cal",
        sub: "events",
        options: ["from": fromStr, "to": toStr],
        flags: [],
        timeoutSec: 25
    )
    guard res.exitCode == 0,
          let obj = try? JSONSerialization.jsonObject(with: res.stdout) as? [String: Any],
          let ok = obj["ok"] as? Bool, ok,
          let events = obj["events"] as? [[String: Any]] else {
        let msg = String(data: res.stderr, encoding: .utf8) ?? String(data: res.stdout, encoding: .utf8) ?? "JXA cal events failed"
        throw CLIError(message: msg.trimmingCharacters(in: .whitespacesAndNewlines))
    }
    return (fromStr, toStr, events)
}

func fetchRemindersForSnapshot(_ store: EKEventStore) throws -> [[String: Any]] {
    if hasReminderFullAccess(store) {
        let items = try fetchReminders(store, calendars: nil).filter { !$0.isCompleted }
        return items.map(serializeReminder)
    }
    let res = try runJXACapture(
        cmd: "rem",
        sub: "list",
        options: ["completed": "false"],
        flags: [],
        timeoutSec: 15
    )
    guard res.exitCode == 0,
          let obj = try? JSONSerialization.jsonObject(with: res.stdout) as? [String: Any],
          let ok = obj["ok"] as? Bool, ok,
          let reminders = obj["reminders"] as? [[String: Any]] else {
        let msg = String(data: res.stderr, encoding: .utf8) ?? String(data: res.stdout, encoding: .utf8) ?? "JXA rem list failed"
        throw CLIError(message: msg.trimmingCharacters(in: .whitespacesAndNewlines))
    }
    return reminders
}

func generateSnapshot(
    _ store: EKEventStore,
    days: Int,
    outURL: URL,
    maxAgeSec: Int?,
    bestEffort: Bool
) throws -> [String: Any] {
    let fm = FileManager.default
    let stampURL = snapshotStampURL()

    if let maxAge = maxAgeSec,
       fm.fileExists(atPath: outURL.path),
       let attrs = try? fm.attributesOfItem(atPath: stampURL.path),
       let mod = attrs[.modificationDate] as? Date,
       Date().timeIntervalSince(mod) < Double(maxAge) {
        return [
            "ok": true,
            "skipped": "fresh",
            "changed": false,
            "path": outURL.path,
        ]
    }

    var existingObj: [String: Any]?
    if let existingData = try? Data(contentsOf: outURL),
       let parsed = try? JSONSerialization.jsonObject(with: existingData) as? [String: Any] {
        existingObj = parsed
    }

    let now = Date()
    let startOfToday = Calendar.current.startOfDay(for: now)
    let toDate = Calendar.current.date(byAdding: .day, value: days, to: startOfToday)
        ?? startOfToday.addingTimeInterval(TimeInterval(days * 86400))
    var fromStr = DateHelper.isoFormatter.string(from: startOfToday)
    var toStr = DateHelper.isoFormatter.string(from: toDate)

    var events: [[String: Any]] = []
    var reminders: [[String: Any]] = []
    var warnings: [String] = []
    let nowStr = DateHelper.isoFormatter.string(from: Date())
    var calendarUpdatedAt: Any = existingObj?["calendarUpdatedAt"] ?? NSNull()
    var remindersUpdatedAt: Any = existingObj?["remindersUpdatedAt"] ?? NSNull()

    do {
        let evRes = try fetchEventsForSnapshot(store, days: days)
        fromStr = evRes.from
        toStr = evRes.to
        events = evRes.events
        calendarUpdatedAt = nowStr
    } catch {
        if !bestEffort { throw error }
        if let prev = existingObj?["events"] as? [[String: Any]] {
            events = prev
        }
        warnings.append("calendar: \(error)")
    }

    do {
        reminders = try fetchRemindersForSnapshot(store)
        remindersUpdatedAt = nowStr
    } catch {
        if !bestEffort { throw error }
        if let prev = existingObj?["reminders"] as? [[String: Any]] {
            reminders = prev
        }
        warnings.append("reminders: \(error)")
    }

    let comparableNew: [String: Any] = [
        "windowDays": days,
        "from": fromStr,
        "to": toStr,
        "events": events,
        "reminders": reminders,
        "warnings": warnings,
    ]
    var unchanged = false
    if let ex = existingObj {
        let comparableOld: [String: Any] = [
            "windowDays": ex["windowDays"] ?? days,
            "from": ex["from"] ?? "",
            "to": ex["to"] ?? "",
            "events": ex["events"] ?? [],
            "reminders": ex["reminders"] ?? [],
            "warnings": ex["warnings"] ?? [],
        ]
        if let d1 = canonicalJSON(comparableNew), let d2 = canonicalJSON(comparableOld), d1 == d2 {
            unchanged = true
        }
    }

    // Touch throttle stamp regardless of whether snapshot content changed.
    if !fm.fileExists(atPath: stampURL.path) {
        fm.createFile(atPath: stampURL.path, contents: Data())
    } else {
        try? fm.setAttributes([.modificationDate: Date()], ofItemAtPath: stampURL.path)
    }

    if unchanged {
        var res: [String: Any] = [
            "ok": true,
            "changed": false,
            "path": outURL.path,
            "eventCount": events.count,
            "reminderCount": reminders.count,
        ]
        if !warnings.isEmpty { res["warnings"] = warnings }
        return res
    }

    var payload: [String: Any] = [
        "ok": true,
        "generatedAt": nowStr,
        "calendarUpdatedAt": calendarUpdatedAt,
        "remindersUpdatedAt": remindersUpdatedAt,
        "windowDays": days,
        "from": fromStr,
        "to": toStr,
        "eventCount": events.count,
        "reminderCount": reminders.count,
        "events": events,
        "reminders": reminders,
    ]
    if !warnings.isEmpty { payload["warnings"] = warnings }

    let outData = try JSONSerialization.data(
        withJSONObject: payload,
        options: [.prettyPrinted, .sortedKeys, .withoutEscapingSlashes]
    )
    try outData.write(to: outURL, options: [.atomic])

    var res: [String: Any] = [
        "ok": true,
        "changed": true,
        "path": outURL.path,
        "eventCount": events.count,
        "reminderCount": reminders.count,
    ]
    if !warnings.isEmpty { res["warnings"] = warnings }
    return res
}

func handleSnapshot(_ store: EKEventStore, parsed: ParsedArgs) throws {
    let days = Int(parsed.options["days"] ?? "30") ?? 30
    let outURL = parsed.options["out"].map { URL(fileURLWithPath: $0) } ?? defaultSnapshotURL()
    let maxAgeSec = parsed.options["max-age-sec"].flatMap { Int($0) }
    let bestEffort = parsed.flags.contains("best-effort")
    let res = try generateSnapshot(store, days: days, outURL: outURL, maxAgeSec: maxAgeSec, bestEffort: bestEffort)
    printJSON(res)
}

// MARK: - Help

func printHelp() {
    let help = """
    eventkit-ctl - Fast native macOS Calendar & Reminders CLI (JSON output)

    USAGE:
      eventkit-ctl status
      eventkit-ctl authorize [--target all|calendar|reminders]
      eventkit-ctl places
      eventkit-ctl snapshot [--days 30] [--out PATH] [--max-age-sec N] [--best-effort]

      eventkit-ctl cal lists
      eventkit-ctl cal events [--from ISO] [--to ISO] [--days N] [--calendar NAME_OR_ID] [--query TEXT]
      eventkit-ctl cal add --title TEXT --start ISO [--end ISO | --duration MIN] [--calendar NAME_OR_ID] [--all-day] [--place KEY_OR_ALIAS | --location TEXT] [--notes TEXT] [--url URL]
      eventkit-ctl cal update --id ID [--title TEXT] [--start ISO] [--end ISO] [--calendar NAME_OR_ID] [--place KEY_OR_ALIAS | --location TEXT] [--notes TEXT] [--url URL] [--span this|future]
      eventkit-ctl cal delete --id ID [--span this|future]

      eventkit-ctl rem lists
      eventkit-ctl rem list [--list NAME_OR_ID] [--completed true|false|all] [--due-before ISO] [--query TEXT]
      eventkit-ctl rem add --title TEXT [--list NAME_OR_ID] [--due ISO] [--priority 0|1|5|9|none|low|medium|high] [--place KEY_OR_ALIAS | --location TEXT] [--lat LAT --lon LON --radius M --proximity enter|leave] [--notes TEXT] [--url URL]
      eventkit-ctl rem update --id ID [--title TEXT] [--list NAME_OR_ID] [--due ISO | --clear-due] [--priority ...] [--place KEY_OR_ALIAS | --location TEXT] [--notes TEXT] [--url URL] [--completed true|false]
      eventkit-ctl rem complete --id ID [--undo]
      eventkit-ctl rem delete --id ID
    """
    print(help)
}

// MARK: - Command Handlers

func handleStatus() {
    let cal = EKEventStore.authorizationStatus(for: .event)
    let rem = EKEventStore.authorizationStatus(for: .reminder)
    printJSON([
        "ok": true,
        "calendar": statusString(cal),
        "reminders": statusString(rem),
    ])
}

func handleAuthorize(_ store: EKEventStore, parsed: ParsedArgs) throws {
    let target = parsed.options["target"] ?? "all"
    var calGranted: Bool?
    var remGranted: Bool?
    if target == "all" || target == "calendar" {
        calGranted = try waitFor { store.requestFullAccessToEvents(completion: $0) }
    }
    if target == "all" || target == "reminders" {
        remGranted = try waitFor { store.requestFullAccessToReminders(completion: $0) }
    }
    if target != "all" && target != "calendar" && target != "reminders" {
        throw CLIError(message: "Invalid --target '\(target)'. Use all, calendar, or reminders.")
    }
    var out: [String: Any] = [
        "ok": true,
        "calendar": statusString(EKEventStore.authorizationStatus(for: .event)),
        "reminders": statusString(EKEventStore.authorizationStatus(for: .reminder)),
    ]
    if let c = calGranted { out["calendarGranted"] = c }
    if let r = remGranted { out["remindersGranted"] = r }
    printJSON(out)
}

func handleCal(_ store: EKEventStore, sub: String, parsed: ParsedArgs) throws {
    let backend = (parsed.options["backend"] ?? "auto").lowercased()
    let isMutation = ["add", "update", "delete"].contains(sub)
    if backend == "jxa" {
        runJXAFallback(cmd: "cal", sub: sub, parsed: parsed, refreshAfter: isMutation, store: store)
    }
    if !hasCalendarFullAccess(store) {
        if backend == "eventkit" {
            throw CLIError(
                message: "Calendar access denied (status: \(statusString(EKEventStore.authorizationStatus(for: .event))))."
            )
        }
        runJXAFallback(cmd: "cal", sub: sub, parsed: parsed, refreshAfter: isMutation, store: store)
    }
    switch sub {
    case "lists":
        let cals = store.calendars(for: .event).map(serializeCalendar)
        printJSON(["ok": true, "calendars": cals])

    case "events":
        let now = Date()
        let startOfToday = Calendar.current.startOfDay(for: now)
        let fromDate = try parsed.options["from"].map(DateHelper.parse) ?? startOfToday
        let toDate: Date
        if let toRaw = parsed.options["to"] {
            toDate = try DateHelper.parse(toRaw)
        } else {
            let days = Int(parsed.options["days"] ?? "7") ?? 7
            toDate = Calendar.current.date(byAdding: .day, value: days, to: fromDate) ?? fromDate.addingTimeInterval(TimeInterval(days * 86400))
        }
        let calendars: [EKCalendar]? = try parsed.options["calendar"].map {
            [try resolveCalendar(store, titleOrId: $0, entityType: .event)]
        }
        let pred = store.predicateForEvents(withStart: fromDate, end: toDate, calendars: calendars)
        var events = store.events(matching: pred).sorted { $0.startDate < $1.startDate }
        if let q = parsed.options["query"]?.lowercased(), !q.isEmpty {
            events = events.filter {
                ($0.title ?? "").lowercased().contains(q)
                    || ($0.location ?? "").lowercased().contains(q)
                    || ($0.notes ?? "").lowercased().contains(q)
            }
        }
        printJSON([
            "ok": true,
            "from": DateHelper.format(fromDate),
            "to": DateHelper.format(toDate),
            "count": events.count,
            "events": events.map(serializeEvent),
        ])

    case "add":
        guard let title = parsed.options["title"], !title.isEmpty else {
            throw CLIError(message: "Missing required --title")
        }
        guard let startRaw = parsed.options["start"] else {
            throw CLIError(message: "Missing required --start")
        }
        let startDate = try DateHelper.parse(startRaw)
        let allDay = parsed.flags.contains("all-day")
        let endDate: Date
        if let endRaw = parsed.options["end"] {
            endDate = try DateHelper.parse(endRaw)
        } else if let durRaw = parsed.options["duration"], let mins = Int(durRaw) {
            endDate = startDate.addingTimeInterval(TimeInterval(mins * 60))
        } else if allDay {
            endDate = Calendar.current.date(byAdding: .day, value: 1, to: Calendar.current.startOfDay(for: startDate)) ?? startDate.addingTimeInterval(86400)
        } else {
            endDate = startDate.addingTimeInterval(3600)
        }

        let targetCal: EKCalendar
        if let calRef = parsed.options["calendar"] {
            targetCal = try resolveCalendar(store, titleOrId: calRef, entityType: .event)
        } else if let def = store.defaultCalendarForNewEvents {
            targetCal = def
        } else {
            throw CLIError(message: "No default calendar for new events.")
        }

        let ev = EKEvent(eventStore: store)
        ev.title = title
        ev.calendar = targetCal
        ev.startDate = startDate
        ev.endDate = endDate
        ev.isAllDay = allDay
        if let loc = parsed.options["location"] { ev.location = loc }
        if let notes = parsed.options["notes"] { ev.notes = notes }
        if let urlStr = parsed.options["url"] { ev.url = URL(string: urlStr) }

        try store.save(ev, span: .thisEvent, commit: true)
        _ = try? generateSnapshot(store, days: 30, outURL: defaultSnapshotURL(), maxAgeSec: nil, bestEffort: true)
        printJSON(["ok": true, "event": serializeEvent(ev)])

    case "update":
        guard let id = parsed.options["id"], !id.isEmpty else {
            throw CLIError(message: "Missing required --id")
        }
        guard let ev = store.event(withIdentifier: id) else {
            throw CLIError(message: "Event not found for id '\(id)'")
        }
        if let title = parsed.options["title"] { ev.title = title }
        if let startRaw = parsed.options["start"] { ev.startDate = try DateHelper.parse(startRaw) }
        if let endRaw = parsed.options["end"] { ev.endDate = try DateHelper.parse(endRaw) }
        if let calRef = parsed.options["calendar"] {
            ev.calendar = try resolveCalendar(store, titleOrId: calRef, entityType: .event)
        }
        if let loc = parsed.options["location"] { ev.location = loc }
        if let notes = parsed.options["notes"] { ev.notes = notes }
        if let urlStr = parsed.options["url"] { ev.url = URL(string: urlStr) }
        let span = try parseSpan(parsed.options["span"])
        try store.save(ev, span: span, commit: true)
        _ = try? generateSnapshot(store, days: 30, outURL: defaultSnapshotURL(), maxAgeSec: nil, bestEffort: true)
        printJSON(["ok": true, "event": serializeEvent(ev)])

    case "delete":
        guard let id = parsed.options["id"], !id.isEmpty else {
            throw CLIError(message: "Missing required --id")
        }
        guard let ev = store.event(withIdentifier: id) else {
            throw CLIError(message: "Event not found for id '\(id)'")
        }
        let span = try parseSpan(parsed.options["span"])
        try store.remove(ev, span: span, commit: true)
        _ = try? generateSnapshot(store, days: 30, outURL: defaultSnapshotURL(), maxAgeSec: nil, bestEffort: true)
        printJSON(["ok": true, "deleted": true, "id": id])

    default:
        throw CLIError(message: "Unknown 'cal' subcommand '\(sub)'. Use lists, events, add, update, or delete.")
    }
}

func handleRem(_ store: EKEventStore, sub: String, parsed: ParsedArgs) throws {
    let backend = (parsed.options["backend"] ?? "auto").lowercased()
    let isMutation = ["add", "update", "complete", "delete"].contains(sub)
    if backend == "jxa" {
        runJXAFallback(cmd: "rem", sub: sub, parsed: parsed, refreshAfter: isMutation, store: store)
    }
    if !hasReminderFullAccess(store) {
        if backend == "eventkit" {
            throw CLIError(
                message: "Reminders access denied (status: \(statusString(EKEventStore.authorizationStatus(for: .reminder))))."
            )
        }
        runJXAFallback(cmd: "rem", sub: sub, parsed: parsed, refreshAfter: isMutation, store: store)
    }
    switch sub {
    case "lists":
        let lists = store.calendars(for: .reminder).map(serializeCalendar)
        printJSON(["ok": true, "lists": lists])

    case "list":
        let calendars: [EKCalendar]? = try parsed.options["list"].map {
            [try resolveCalendar(store, titleOrId: $0, entityType: .reminder)]
        }
        var items = try fetchReminders(store, calendars: calendars)
        let compFilter = (parsed.options["completed"] ?? "false").lowercased()
        switch compFilter {
        case "false": items = items.filter { !$0.isCompleted }
        case "true": items = items.filter { $0.isCompleted }
        case "all": break
        default: throw CLIError(message: "Invalid --completed '\(compFilter)'. Use true, false, or all.")
        }

        if let dueBeforeRaw = parsed.options["due-before"] {
            let cutoff = try DateHelper.parse(dueBeforeRaw)
            let cal = Calendar.current
            items = items.filter {
                guard let comps = $0.dueDateComponents, let d = cal.date(from: comps) else { return false }
                return d <= cutoff
            }
        }
        if let q = parsed.options["query"]?.lowercased(), !q.isEmpty {
            items = items.filter {
                ($0.title ?? "").lowercased().contains(q)
                    || ($0.notes ?? "").lowercased().contains(q)
            }
        }
        printJSON([
            "ok": true,
            "count": items.count,
            "reminders": items.map(serializeReminder),
        ])

    case "add":
        guard let title = parsed.options["title"], !title.isEmpty else {
            throw CLIError(message: "Missing required --title")
        }
        let targetList: EKCalendar
        if let listRef = parsed.options["list"] {
            targetList = try resolveCalendar(store, titleOrId: listRef, entityType: .reminder)
        } else if let def = store.defaultCalendarForNewReminders() {
            targetList = def
        } else {
            throw CLIError(message: "No default reminder list configured.")
        }

        let rem = EKReminder(eventStore: store)
        rem.title = title
        rem.calendar = targetList
        if let dueRaw = parsed.options["due"] {
            let dueDate = try DateHelper.parse(dueRaw)
            rem.dueDateComponents = Calendar.current.dateComponents(
                [.year, .month, .day, .hour, .minute, .second],
                from: dueDate
            )
        }
        if let prioRaw = parsed.options["priority"] {
            rem.priority = try parsePriority(prioRaw)
        }
        if let notes = parsed.options["notes"] { rem.notes = notes }
        if let urlStr = parsed.options["url"] { rem.url = URL(string: urlStr) }
        if let loc = try buildStructuredLocation(options: parsed.options) {
            let alarm = EKAlarm()
            alarm.structuredLocation = loc
            alarm.proximity = try parseProximity(parsed.options["proximity"])
            rem.addAlarm(alarm)
        }

        try store.save(rem, commit: true)
        _ = try? generateSnapshot(store, days: 30, outURL: defaultSnapshotURL(), maxAgeSec: nil, bestEffort: true)
        printJSON(["ok": true, "reminder": serializeReminder(rem)])

    case "update":
        guard let id = parsed.options["id"], !id.isEmpty else {
            throw CLIError(message: "Missing required --id")
        }
        let rem = try findReminder(store, id: id)
        if let title = parsed.options["title"] { rem.title = title }
        if let listRef = parsed.options["list"] {
            rem.calendar = try resolveCalendar(store, titleOrId: listRef, entityType: .reminder)
        }
        if parsed.flags.contains("clear-due") {
            rem.dueDateComponents = nil
        } else if let dueRaw = parsed.options["due"] {
            let dueDate = try DateHelper.parse(dueRaw)
            rem.dueDateComponents = Calendar.current.dateComponents(
                [.year, .month, .day, .hour, .minute, .second],
                from: dueDate
            )
        }
        if let prioRaw = parsed.options["priority"] {
            rem.priority = try parsePriority(prioRaw)
        }
        if let notes = parsed.options["notes"] { rem.notes = notes }
        if let urlStr = parsed.options["url"] { rem.url = URL(string: urlStr) }
        if let compRaw = parsed.options["completed"] {
            rem.isCompleted = try parseBool(compRaw)
        }
        if let loc = try buildStructuredLocation(options: parsed.options) {
            for existing in rem.alarms ?? [] where existing.structuredLocation != nil {
                rem.removeAlarm(existing)
            }
            let alarm = EKAlarm()
            alarm.structuredLocation = loc
            alarm.proximity = try parseProximity(parsed.options["proximity"])
            rem.addAlarm(alarm)
        }
        try store.save(rem, commit: true)
        _ = try? generateSnapshot(store, days: 30, outURL: defaultSnapshotURL(), maxAgeSec: nil, bestEffort: true)
        printJSON(["ok": true, "reminder": serializeReminder(rem)])

    case "complete":
        guard let id = parsed.options["id"], !id.isEmpty else {
            throw CLIError(message: "Missing required --id")
        }
        let rem = try findReminder(store, id: id)
        rem.isCompleted = !parsed.flags.contains("undo")
        try store.save(rem, commit: true)
        _ = try? generateSnapshot(store, days: 30, outURL: defaultSnapshotURL(), maxAgeSec: nil, bestEffort: true)
        printJSON(["ok": true, "reminder": serializeReminder(rem)])

    case "delete":
        guard let id = parsed.options["id"], !id.isEmpty else {
            throw CLIError(message: "Missing required --id")
        }
        let rem = try findReminder(store, id: id)
        try store.remove(rem, commit: true)
        _ = try? generateSnapshot(store, days: 30, outURL: defaultSnapshotURL(), maxAgeSec: nil, bestEffort: true)
        printJSON(["ok": true, "deleted": true, "id": id])

    default:
        throw CLIError(message: "Unknown 'rem' subcommand '\(sub)'. Use lists, list, add, update, complete, or delete.")
    }
}

// MARK: - Main

do {
    var parsed = try parseArgs(Array(CommandLine.arguments.dropFirst()))
    if parsed.flags.contains("help") || parsed.positionals.isEmpty {
        printHelp()
        exit(0)
    }
    try resolvePlaceOptions(&parsed)

    let store = EKEventStore()
    let cmd = parsed.positionals[0]

    switch cmd {
    case "status":
        handleStatus()
    case "authorize":
        try handleAuthorize(store, parsed: parsed)
    case "places":
        handlePlaces()
    case "snapshot":
        try handleSnapshot(store, parsed: parsed)
    case "cal":
        guard parsed.positionals.count >= 2 else {
            throw CLIError(message: "Missing 'cal' subcommand. Use lists, events, add, update, or delete.")
        }
        try handleCal(store, sub: parsed.positionals[1], parsed: parsed)
    case "rem":
        guard parsed.positionals.count >= 2 else {
            throw CLIError(message: "Missing 'rem' subcommand. Use lists, list, add, update, complete, or delete.")
        }
        try handleRem(store, sub: parsed.positionals[1], parsed: parsed)
    default:
        throw CLIError(message: "Unknown command '\(cmd)'. Run 'eventkit-ctl --help'.")
    }
} catch {
    fail(String(describing: error))
}
