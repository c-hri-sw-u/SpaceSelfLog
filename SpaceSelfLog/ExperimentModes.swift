import Foundation

// MARK: - Experiment Context & Protocol

struct ExperimentContext {
    // Previous activity labels (already formatted), newest last
    let previousLabels: [String]
    // How many labels to include for continuity prompts
    let includeCount: Int
}

// Structured formatted output used across experiments
struct FormattedOutput: Codable {
    let activityLabel: String
    let location: String?
    let handsInTheView: Bool?
    let objects: [String]?
    init(activityLabel: String, location: String? = nil, handsInTheView: Bool? = nil, objects: [String]? = nil) {
        self.activityLabel = activityLabel
        self.location = location
        self.handsInTheView = handsInTheView
        self.objects = objects
    }
}

protocol ExperimentMode {
    var id: Int { get }
    var expectedRawOutputDescription: String { get }
    func defaultPrompt(context: ExperimentContext?) -> String
    func validate(_ output: String) -> Bool
    func format(_ output: String) -> FormattedOutput
}

// MARK: - Helpers

fileprivate func sanitizeSingleWord(_ text: String) -> String? {
    let cleaned = text.trimmingCharacters(in: .whitespacesAndNewlines)
    guard !cleaned.isEmpty else { return nil }
    let words = cleaned.components(separatedBy: .whitespacesAndNewlines)
    guard let first = words.first, !first.isEmpty else { return nil }
    let englishOnly = first.filter { $0.isLetter }
    guard !englishOnly.isEmpty else { return nil }
    return englishOnly.lowercased()
}

fileprivate func toIng(_ base: String) -> String {
    let word = base.lowercased()
    if word.hasSuffix("ing") { return word }
    // naive -ing rules: drop trailing 'e', double final consonant if CVC
    if word.hasSuffix("e") {
        let stem = String(word.dropLast())
        return stem + "ing"
    }
    // simple CVC check
    func isVowel(_ c: Character) -> Bool { "aeiou".contains(c) }
    if word.count >= 3 {
        let chars = Array(word)
        let c1 = chars[chars.count - 3]
        let c2 = chars[chars.count - 2]
        let c3 = chars[chars.count - 1]
        if !isVowel(c1) && isVowel(c2) && !isVowel(c3) {
            return word + String(c3) + "ing"
        }
    }
    return word + "ing"
}

// Robustly extract a JSON object from strings that may include code fences or extra text
fileprivate func extractJSONObject(from output: String) -> [String: Any]? {
    let trimmed = output.trimmingCharacters(in: .whitespacesAndNewlines)
    // Try direct parse
    if let data = trimmed.data(using: .utf8),
       let obj = try? JSONSerialization.jsonObject(with: data, options: []) as? [String: Any] {
        return obj
    }
    // Remove common code fence markers
    var cleaned = trimmed.replacingOccurrences(of: "```json", with: "")
    cleaned = cleaned.replacingOccurrences(of: "```", with: "")
    // Try parse again
    if let data2 = cleaned.data(using: .utf8),
       let obj2 = try? JSONSerialization.jsonObject(with: data2, options: []) as? [String: Any] {
        return obj2
    }
    // Fallback: take substring between first '{' and last '}'
    if let start = cleaned.firstIndex(of: "{"), let end = cleaned.lastIndex(of: "}") {
        let jsonStr = String(cleaned[start...end])
        if let data3 = jsonStr.data(using: .utf8),
           let obj3 = try? JSONSerialization.jsonObject(with: data3, options: []) as? [String: Any] {
            return obj3
        }
    }
    return nil
}

// MARK: - Experiment 1: Single word (ing preferred)

struct Experiment1: ExperimentMode {
    let id: Int = 1
    let expectedRawOutputDescription: String = "Single English word representing activity (prefer -ing)"
    func defaultPrompt(context: ExperimentContext?) -> String {
        return "What am I doing based on this image? Respond with a single English word with -ing."
    }
    func validate(_ output: String) -> Bool {
        return sanitizeSingleWord(output) != nil
    }
    func format(_ output: String) -> FormattedOutput {
        guard let word = sanitizeSingleWord(output) else { return FormattedOutput(activityLabel: "unknown") }
        return FormattedOutput(activityLabel: toIng(word))
    }
}

// MARK: - Experiment 2: Continuity with previous labels

struct Experiment2: ExperimentMode {
    let id: Int = 2
    let expectedRawOutputDescription: String = "Single English -ing word emphasizing temporal continuity"
    func defaultPrompt(context: ExperimentContext?) -> String {
        let labels: [String]
        let n: Int
        if let ctx = context {
            n = max(1, ctx.includeCount)
            labels = ctx.previousLabels.suffix(n)
        } else {
            n = 3
            labels = []
        }
        let history = labels.isEmpty ? "(no prior labels)" : labels.joined(separator: ", ")
        return "Considering previous activity labels: [\(history)]. Based on this image, respond with a single English -ing word that best continues the sequence (avoid abrupt switches unless needed)."
    }
    func validate(_ output: String) -> Bool {
        guard let word = sanitizeSingleWord(output) else { return false }
        return toIng(word).hasSuffix("ing")
    }
    func format(_ output: String) -> FormattedOutput {
        guard let word = sanitizeSingleWord(output) else { return FormattedOutput(activityLabel: "unknown") }
        return FormattedOutput(activityLabel: toIng(word))
    }
}

// MARK: - Experiment 3: JSON schema { objects, location, handsInTheView, activityLabel }

struct Experiment3: ExperimentMode {
    let id: Int = 3
    let expectedRawOutputDescription: String = "Strict JSON with objects list (array of strings)"
    func defaultPrompt(context: ExperimentContext?) -> String {
        return "Analyze the image and return STRICT JSON with keys: objects (JSON array of strings; list all identifiable objects, use [] if none), location (select from [bedroom, kitchen, bathroom, living room, dining room, storeroom]), handsInTheView (boolean), activityLabel (a single English -ing word). Return only raw JSON (do NOT use code fences like ```json), no extra text. Example: {\"objects\": [\"knife\", \"tomato\"], \"location\": \"kitchen\", \"handsInTheView\": true, \"activityLabel\": \"cutting\"}."
    }
    func validate(_ output: String) -> Bool {
        guard let obj = extractJSONObject(from: output) else { return false }

        // activityLabel: single English -ing word
        guard let labelRaw = obj["activityLabel"] as? String,
              let sanitized = sanitizeSingleWord(labelRaw) else { return false }
        let ing = toIng(sanitized)
        guard ing.hasSuffix("ing") else { return false }

        // location: one of predefined values (case-insensitive)
        let allowedLocations: Set<String> = [
            "bedroom", "kitchen", "bathroom", "living room", "dining room", "storeroom"
        ]
        guard let locationRaw = obj["location"] as? String,
              allowedLocations.contains(locationRaw.lowercased()) else { return false }

        // handsInTheView: boolean
        guard obj["handsInTheView"] is Bool else { return false }

        // objects: must be an array of strings (can be empty)
        guard let objects = obj["objects"] as? [Any] else { return false }
        for item in objects {
            guard item is String else { return false }
        }
        return true
    }
    func format(_ output: String) -> FormattedOutput {
        guard let obj = extractJSONObject(from: output) else {
            return FormattedOutput(activityLabel: "unknown")
        }

        // activityLabel: sanitize to single -ing word
        let labelRaw = (obj["activityLabel"] as? String) ?? ""
        let label = sanitizeSingleWord(labelRaw).map { toIng($0) } ?? "unknown"

        // location: trim, lowercase; keep even if not in allowed set (simple correction)
        var locationValue: String? = nil
        if let loc = obj["location"] as? String {
            let trimmed = loc.trimmingCharacters(in: .whitespacesAndNewlines)
            if !trimmed.isEmpty { locationValue = trimmed.lowercased() }
        }

        // handsInTheView: accept bool, "true"/"false" strings, or 0/1 numbers
        var handsValue: Bool? = nil
        if let hands = obj["handsInTheView"] {
            if let b = hands as? Bool {
                handsValue = b
            } else if let s = hands as? String {
                let lower = s.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
                if lower == "true" { handsValue = true }
                else if lower == "false" { handsValue = false }
            } else if let n = hands as? NSNumber {
                handsValue = n.intValue != 0
            }
        }

        // objects: ensure array of strings; accept single string by wrapping
        var objectsValue: [String]? = nil
        if let arr = obj["objects"] as? [Any] {
            let strings = arr.compactMap { element -> String? in
                if let s = element as? String {
                    let t = s.trimmingCharacters(in: .whitespacesAndNewlines)
                    return t.isEmpty ? nil : t.lowercased()
                }
                return nil
            }
            if !strings.isEmpty { objectsValue = Array(Set(strings)).sorted() } else { objectsValue = [] }
        } else if let single = obj["objects"] as? String {
            let t = single.trimmingCharacters(in: .whitespacesAndNewlines)
            if !t.isEmpty { objectsValue = [t.lowercased()] }
        }

        return FormattedOutput(activityLabel: label, location: locationValue, handsInTheView: handsValue, objects: objectsValue)
    }
}

// MARK: - Registry

enum ExperimentRegistry {
    // Centralized registry of available experiments
    static let all: [ExperimentMode] = [
        Experiment1(),
        Experiment2(),
        Experiment3()
    ]

    // Convenience: list of IDs and max ID
    static var ids: [Int] { all.map { $0.id }.sorted() }
    static var maxId: Int { ids.max() ?? 1 }
    static var minId: Int { ids.min() ?? 1 }

    // Lookup by id; fallback to first available
    static func mode(for index: Int) -> ExperimentMode {
        return all.first(where: { $0.id == index }) ?? (all.first ?? Experiment1())
    }
}