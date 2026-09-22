// เล่นเสียงตอบและจับเสียงไมโครโฟนผ่านยูนิต voice processing ตัวเดียวกัน
//
// การตัดเสียงสะท้อนต้องให้ยูนิตรู้ว่าลำโพงกำลังปล่อยคลื่นอะไรออกไป จึงต้องเล่นเสียง
// ผ่าน engine เดียวกับที่จับเสียง ถ้าเล่นด้วย afplay ซึ่งเป็นอีก process ยูนิตจะไม่มี
// สัญญาณอ้างอิงให้ลบ ไมค์ก็จะได้ยินเสียงตัวเองอยู่ดี
//
// stdout: PCM float32 ช่องเดียว 16000 เฮิรตซ์ ไม่มีส่วนหัวไฟล์
// stdin:  คำสั่งทีละบรรทัด  play <รหัส> <พาธ> | stop | quit
// stderr: ready | done <รหัส> | error <ข้อความ>

import AVFoundation
import Foundation

let targetRate = 16000.0
let fallbackRate = 48000.0
let engine = AVAudioEngine()
let input = engine.inputNode
let output = engine.outputNode
let player = AVAudioPlayerNode()
let reportLock = NSLock()

func report(_ line: String) {
    reportLock.lock()
    fputs(line + "\n", stderr)
    fflush(stderr)
    reportLock.unlock()
}

func fail(_ message: String) -> Never {
    report("error \(message)")
    exit(1)
}

do {
    // ต้องเปิดทั้งสองขา ไม่งั้นขาเข้ากับขาออกเป็นยูนิตแยกกัน ยูนิตขาเข้าจะไม่รู้ว่า
    // ลำโพงปล่อยอะไรออกไปและตัดเสียงสะท้อนไม่ได้เลย
    try input.setVoiceProcessingEnabled(true)
    try output.setVoiceProcessingEnabled(true)
} catch {
    fail("เปิด voice processing ไม่สำเร็จ: \(error)")
}

// ปิดการปรับระดับเสียงอัตโนมัติ เพราะทำให้ความดังแกว่งจน VAD ตัดสินพลาด
if #available(macOS 14.0, *) {
    input.isVoiceProcessingAGCEnabled = false
    // ยูนิตนี้กดเสียงแอปอื่นให้เบาลงเองตามค่าเริ่มต้น ซึ่งไม่เกี่ยวกับงานเรา
    input.voiceProcessingOtherAudioDuckingConfiguration =
        AVAudioVoiceProcessingOtherAudioDuckingConfiguration(
            enableAdvancedDucking: false, duckingLevel: .min)
}

// ต้องอ่านอัตราสุ่มหลังเปิด voice processing แล้ว และบังคับให้ทั้งกราฟใช้อัตราเดียวกับ
// อุปกรณ์ ถ้าปล่อยให้มิกเซอร์ตั้งเองมันจะไปที่ 44100 แล้วยูนิตขาออก init ไม่ผ่าน (-10875)
let deviceRate = output.inputFormat(forBus: 0).sampleRate
guard let playFormat = AVAudioFormat(
    standardFormatWithSampleRate: deviceRate > 0 ? deviceRate : fallbackRate, channels: 1)
else { fail("สร้างรูปแบบเสียงขาออกไม่สำเร็จ") }

engine.attach(player)
engine.connect(player, to: engine.mainMixerNode, format: playFormat)
engine.connect(engine.mainMixerNode, to: output, format: playFormat)

let inputFormat = input.outputFormat(forBus: 0)
guard let captureFormat = AVAudioFormat(
    commonFormat: .pcmFormatFloat32, sampleRate: targetRate, channels: 1, interleaved: false),
    let captureConverter = AVAudioConverter(from: inputFormat, to: captureFormat)
else { fail("สร้างตัวแปลงรูปแบบเสียงเข้าไม่สำเร็จ") }

// voice processing ส่งมาหลายช่อง (7-9 ช่อง) ช่องแรกคือเสียงที่ตัดเสียงสะท้อนแล้ว
// ถ้าไม่บอกว่าเอาช่องไหน ตัวแปลงจะคายความเงียบออกมาเฉย ๆ โดยไม่แจ้งข้อผิดพลาด
captureConverter.channelMap = [0]

let standardOutput = FileHandle.standardOutput

input.installTap(onBus: 0, bufferSize: 1024, format: inputFormat) { buffer, _ in
    let capacity = AVAudioFrameCount(
        Double(buffer.frameLength) * targetRate / inputFormat.sampleRate + 64)
    guard let converted = AVAudioPCMBuffer(pcmFormat: captureFormat, frameCapacity: capacity)
    else { return }

    var consumed = false
    var error: NSError?
    captureConverter.convert(to: converted, error: &error) { _, status in
        if consumed {
            status.pointee = .noDataNow
            return nil
        }
        consumed = true
        status.pointee = .haveData
        return buffer
    }
    if error != nil || converted.frameLength == 0 { return }

    guard let channel = converted.floatChannelData?[0] else { return }
    let bytes = Int(converted.frameLength) * MemoryLayout<Float>.size
    standardOutput.write(Data(bytes: channel, count: bytes))
}

/// อ่านไฟล์เสียงทั้งไฟล์มาเป็นบัฟเฟอร์ที่ตรงรูปแบบซึ่งต่อไว้กับมิกเซอร์
func decode(path: String) -> AVAudioPCMBuffer? {
    guard let file = try? AVAudioFile(forReading: URL(fileURLWithPath: path)) else {
        report("error อ่านไฟล์เสียงไม่ได้: \(path)")
        return nil
    }
    let length = AVAudioFrameCount(file.length)
    guard length > 0,
          let source = AVAudioPCMBuffer(pcmFormat: file.processingFormat, frameCapacity: length)
    else { return nil }
    do {
        try file.read(into: source)
    } catch {
        report("error ถอดรหัสเสียงไม่สำเร็จ: \(error)")
        return nil
    }
    if file.processingFormat == playFormat { return source }

    // ต้องแปลงอัตราสุ่มให้ตรงกับที่ต่อไว้ ไม่งั้นเสียงจะเพี้ยนหรือไม่ออกเลย
    let ratio = playFormat.sampleRate / file.processingFormat.sampleRate
    let capacity = AVAudioFrameCount(Double(length) * ratio) + 4096
    guard let converter = AVAudioConverter(from: file.processingFormat, to: playFormat),
          let converted = AVAudioPCMBuffer(pcmFormat: playFormat, frameCapacity: capacity)
    else { return nil }

    var consumed = false
    var error: NSError?
    converter.convert(to: converted, error: &error) { _, status in
        if consumed {
            status.pointee = .endOfStream
            return nil
        }
        consumed = true
        status.pointee = .haveData
        return source
    }
    if error != nil || converted.frameLength == 0 {
        report("error แปลงอัตราสุ่มไม่สำเร็จ")
        return nil
    }
    return converted
}

func schedule(token: String, path: String) {
    guard let buffer = decode(path: path) else {
        report("done \(token)")
        return
    }
    player.scheduleBuffer(buffer, completionCallbackType: .dataPlayedBack) { _ in
        report("done \(token)")
    }
    if !player.isPlaying {
        player.play()
    }
}

do {
    try engine.start()
} catch {
    fail("เริ่มรับเสียงไม่สำเร็จ: \(error)")
}

report("ready")

// อ่านคำสั่งบนเธรดหลัก จบเองเมื่อฝั่ง Python ปิด stdin
while let line = readLine(strippingNewline: true) {
    let parts = line.split(separator: " ", maxSplits: 2).map(String.init)
    switch parts.first {
    case "play" where parts.count == 3:
        schedule(token: parts[1], path: parts[2])
    case "stop":
        player.stop()
    case "quit":
        engine.stop()
        exit(0)
    default:
        report("error คำสั่งไม่รู้จัก: \(line)")
    }
}

engine.stop()
