// จับเสียงไมโครโฟนพร้อมตัดเสียงสะท้อนจากลำโพง แล้วส่งออกทาง stdout
//
// ใช้ voice processing ของระบบ ซึ่งเป็นตัวเดียวกับที่แอปประชุมใช้
// ทำให้ไมค์ไม่ได้ยินเสียงที่เราเล่นออกลำโพงเอง จึงพูดแทรกได้โดยไม่ต้องใส่หูฟัง
//
// ส่งออกเป็น PCM float32 ช่องเดียว 16000 เฮิรตซ์ ไม่มีส่วนหัวไฟล์
// ใช้: swift scripts/voice/capture_aec.swift

import AVFoundation
import Foundation

let targetRate = 16000.0
let engine = AVAudioEngine()
let input = engine.inputNode

do {
    try input.setVoiceProcessingEnabled(true)
} catch {
    fputs("เปิด voice processing ไม่สำเร็จ: \(error)\n", stderr)
    exit(1)
}

// ปิดการปรับระดับเสียงอัตโนมัติ เพราะทำให้ความดังแกว่งจน VAD ตัดสินพลาด
if #available(macOS 14.0, *) {
    input.isVoiceProcessingAGCEnabled = false
}

let inputFormat = input.outputFormat(forBus: 0)
guard let outputFormat = AVAudioFormat(
    commonFormat: .pcmFormatFloat32,
    sampleRate: targetRate,
    channels: 1,
    interleaved: false
), let converter = AVAudioConverter(from: inputFormat, to: outputFormat) else {
    fputs("สร้างตัวแปลงรูปแบบเสียงไม่สำเร็จ\n", stderr)
    exit(1)
}

let standardOutput = FileHandle.standardOutput

input.installTap(onBus: 0, bufferSize: 1024, format: inputFormat) { buffer, _ in
    let capacity = AVAudioFrameCount(
        Double(buffer.frameLength) * targetRate / inputFormat.sampleRate + 64)
    guard let converted = AVAudioPCMBuffer(pcmFormat: outputFormat, frameCapacity: capacity)
    else { return }

    var consumed = false
    var error: NSError?
    converter.convert(to: converted, error: &error) { _, status in
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

do {
    try engine.start()
} catch {
    fputs("เริ่มรับเสียงไม่สำเร็จ: \(error)\n", stderr)
    exit(1)
}

fputs("ready\n", stderr)
RunLoop.current.run()
