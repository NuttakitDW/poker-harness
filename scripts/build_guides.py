from __future__ import annotations

import json
import re
from pathlib import Path

from validate_harness import prose_only, source_page_sections

ROOT = Path(__file__).resolve().parents[1]
def source_briefs() -> list[dict]:
    manifest = json.loads((ROOT / "harnesses/source-manifest.json").read_text())
    return [{"id": book["id"], "title": book["title"], "pages": book["pdf_pages"]} for book in manifest["books"]]

BRIEFS = source_briefs()

# Each row: English heading | Thai heading | English lesson | Thai lesson | phrase to locate.
DATA = {
"pokercoaching-cash-game-cheat-sheet": [
 ("Cash fundamentals", "พื้นฐานเกมเงินสด", "The sheet asks players to value bet when weaker hands call, consider opponent ranges, and adjust preflop play to effective stacks. Its 10:1 implied-odds cue for small pairs and 20:1 for suited connectors are author heuristics, not universal thresholds.", "ชีตชวนให้เบตเพื่อมูลค่าเมื่อมือที่อ่อนกว่าคอล พิจารณาช่วงไพ่คู่ต่อสู้ และปรับก่อนฟลอปตามเงินกองที่มีผล คำแนะนำ implied odds 10:1 สำหรับคู่เล็กและ 20:1 สำหรับไพ่เรียงดอกเป็นแนวทางผู้เขียน ไม่ใช่เกณฑ์สากล", "Cash Game"),
 ("Opponent adaptation", "ปรับตามคู่ต่อสู้", "The sheet separates common player types and asks for responses to their observed tendencies. Use observed ranges and action history before applying any broad label.", "ชีตแยกคู่ต่อสู้หลายประเภทและเสนอวิธีตอบโต้ตามพฤติกรรมที่สังเกตได้ ให้ดูช่วงไพ่และประวัติการเล่นก่อนใช้ป้ายเรียกกว้าง ๆ", "Against"),
 ("Visual hand rankings", "ลำดับไพ่แบบภาพ", "Page four illustrates poker hand rankings with card images. Read suits and exact example cards from the original PDF; OCR is unreliable for card graphics.", "หน้าสี่แสดงลำดับไพ่ด้วยภาพไพ่ ต้องดูดอกและไพ่ตัวอย่างจาก PDF ต้นฉบับ เพราะ OCR อ่านรูปไพ่ไม่เชื่อถือได้", "Poker Hand Rankings"),
 ("Session review and resources", "ทบทวนเซสชันและแหล่งเรียนรู้", "Page three prompts bankroll, sleep, note-taking, and post-session review. Its 3,000–5,000 BB bankroll suggestion is a source claim, not a guarantee. Page five lists additional resources. Cash decisions still require effective stack and rake assumptions.", "หน้าสามชวนตรวจเงินทุน การนอน การจดมือ และการทบทวนหลังเล่น คำแนะนำทุน 3,000–5,000 BB เป็นคำกล่าวในต้นฉบับ ไม่รับประกันผล หน้าห้ารวมแหล่งเรียนรู้ การตัดสินใจเกมเงินสดยังต้องระบุเงินกองที่มีผลและเรก", "Things to Focus On"),
],
"pokercoaching-tournament-cheat-sheet": [
 ("Fundamentals and stack depth", "พื้นฐานและขนาดเงินกอง", "The sheet asks players to monitor opponents, value bet when weaker hands call, and alter preflop ranges with effective stack size. Its small-pair 10:1 implied-odds rule is an author heuristic, not a universal threshold.", "ชีตชวนให้สังเกตคู่ต่อสู้ เบตเพื่อมูลค่าเมื่อมือที่อ่อนกว่าคอล และปรับช่วงไพ่ก่อนฟลอปตามเงินกองที่มีผล กฎ implied odds 10:1 สำหรับคู่เล็กเป็นแนวทางของผู้เขียน ไม่ใช่เกณฑ์สากล", "Tournament Fundamentals"),
 ("Four opponent types", "คู่ต่อสู้สี่ประเภท", "The second page offers different adjustments against splashy passive, overly aggressive, weak tight, and capable players. Some suggestions are strong generalizations; verify a specific opponent's actual frequencies.", "หน้าสองเสนอการปรับตามผู้เล่นหลวมรับ บุกเกินไป แน่นอ่อน และผู้เล่นเก่ง บางคำแนะนำเหมารวมแรง จึงต้องตรวจความถี่จริงของคู่ต่อสู้รายนั้น", "Exploits for Common Player Types"),
 ("Before, during, and after play", "ก่อน ระหว่าง และหลังแข่ง", "The third page prompts bankroll, sleep, preparation, note-taking, and hand review. Its 50–100 buy-in bankroll figure is a source claim, not a guarantee for any payout or variance structure.", "หน้าสามชวนตรวจเงินทุน การนอน การเตรียมตัว การจดมือ และการทบทวน ตัวเลขเงินทุน 50–100 บายอินเป็นคำแนะนำในต้นฉบับ ไม่รับประกันว่าเหมาะกับโครงสร้างรางวัลและความผันผวนทุกแบบ", "Things to Focus On"),
 ("Visual hand rankings", "ลำดับไพ่แบบภาพ", "Page four illustrates poker hand rankings with card images. Read suits and exact example cards from the original PDF; OCR is unreliable for card graphics. This page does not provide a tournament push/fold chart.", "หน้าสี่แสดงลำดับไพ่ด้วยภาพไพ่ ต้องดูดอกและไพ่ตัวอย่างจาก PDF ต้นฉบับ เพราะ OCR อ่านรูปไพ่ไม่เชื่อถือได้ หน้านี้ไม่มีตาราง shove/fold ทัวร์นาเมนต์", "Poker Hand Rankings"),
 ("Resource page label", "ป้ายหน้าทรัพยากร", "The last page lists additional resources but bears a Cash Game Cheat Sheet heading. The preceding four tournament pages and PDF filename establish this document's identity; the final heading appears to be a copy-editing error.", "หน้าสุดท้ายรวมทรัพยากรเพิ่มเติมแต่ใช้หัวว่า Cash Game Cheat Sheet สี่หน้าก่อนหน้าและชื่อไฟล์ระบุชัดว่าเป็นเอกสารทัวร์นาเมนต์ หัวหน้าสุดท้ายจึงดูเป็นข้อผิดพลาดในการจัดทำ", "Additional Resources"),
],
"thai-document-915850": [
 ("Short stack tradeoffs", "ข้อได้เปรียบและข้อจำกัดของสแต็กสั้น", "The author discusses 20–60bb cash-game stacks: preflop three-bets can commit a larger share of the stack, while speculative draws have less implied-odds upside.", "ผู้เขียนกล่าวถึงเงินกอง 20–60 บิ๊กบลายด์: การสามเบตกินสัดส่วนเงินกองมากขึ้น แต่ไพ่รอลุ้นมีโอกาสเก็บกำไรต่อเมื่อเข้าไพ่น้อยลง", "จุดแข็งจุดอ่อน"),
 ("Starting hands and three-bets", "ไพ่เริ่มต้นและการรับมือสามเบต", "The text lists premium, broadway, suited connector, and pocket-pair examples, then prefers selective all-in decisions over frequent short-stack calls to three-bets. These are examples, not validated charts.", "เอกสารยกตัวอย่างไพ่พรีเมียม ไพ่บรอดเวย์ ไพ่เรียงดอกเดียวกัน และคู่ในมือ แล้วเสนอให้เลือกจังหวะออลอินมากกว่าคอลสามเบตบ่อย ๆ รายการนี้เป็นตัวอย่าง ไม่ใช่ตารางช่วงไพ่ที่ผ่านการพิสูจน์", "มาถึง hand หลัก"),
 ("Bluffs and targets", "การบลัฟและเลือกคู่ต่อสู้", "The author describes a dry K-7-4 flop bluff and recommends avoiding opponents who call too widely or raise erratically. Claimed fold percentages are anecdotes, not measured frequencies.", "ผู้เขียนยกตัวอย่างบลัฟบนฟลอป K-7-4 และเตือนเรื่องผู้เล่นที่คอลกว้างหรือเรสโดยคาดเดายาก ตัวเลขโอกาสหมอบในต้นฉบับเป็นคำกล่าวอ้าง ไม่ใช่สถิติที่ตรวจสอบแล้ว", "Shotstack บลัฟได้ไหม"),
 ("Table selection and stack arithmetic", "การเลือกโต๊ะและคณิตศาสตร์เงินกอง", "The document advises observing player types and seeking position on weak opponents. It also claims doubling up and leaving protects profit. Authored mathematical correction for a no-rake NLHE cash game with 20–60bb effective stacks: if each all-in is fair at 50/50, leaving after a win creates no positive EV; effective stacks limit the amount at risk per hand. Tournament payouts are not involved.", "เอกสารแนะนำให้สังเกตชนิดผู้เล่นและหาตำแหน่งทางซ้ายของคู่ต่อสู้ที่อ่อนกว่า อีกทั้งอ้างว่าดับเบิลอัปแล้วลุกช่วยรักษากำไร ข้อแก้ไขทางคณิตศาสตร์ที่ผู้จัดทำเขียนเองสำหรับเกมเงินสด NLHE ไม่มีเรก เงินกองที่มีผล 20–60bb: หากออลอินแต่ละครั้งยุติธรรม 50/50 การเลิกหลังชนะไม่เพิ่ม EV เงินกองที่มีผลจำกัดเงินที่เสี่ยงต่อมือ กรณีนี้ไม่เกี่ยวกับรางวัลทัวร์นาเมนต์", "เทคนิคเพิ่มเติม"),
 ("Scope note", "ขอบเขตเนื้อหา", "The final line previews a future five-card PLO article; this six-page file contains no PLO lesson.", "บรรทัดท้ายเพียงเกริ่นว่าจะเขียนเรื่อง PLO ห้าใบในอนาคต เอกสารหกหน้านี้ไม่มีบทเรียน PLO", "plo 5 card"),
],
"getting-the-answer-key": [
 ("Answer-key access", "วิธีเข้าถึงเฉลย", "This one-page leaflet points to a locked Google Sheet and a downloadable version; it does not contain answers. Check one question early in each section, then the entire section, as the author suggests.", "ใบแทรกหนึ่งหน้านี้ชี้ไปยัง Google Sheet ที่ล็อกไว้และฉบับดาวน์โหลด แต่ไม่มีเฉลยในตัว ผู้เขียนแนะนำให้ตรวจคำตอบข้อแรกของแต่ละหมวด แล้วตรวจทั้งหมวดเมื่อทำเสร็จ", "The Answer Key"),
],
"getting-the-spreadsheets": [
 ("Spreadsheet access", "วิธีเข้าถึงสเปรดชีต", "This is a one-page instruction and offer for SplitSuit spreadsheets, with a stated name-your-price checkout and a quick-start guide. It is not the spreadsheet itself, so no formulas or outputs can be verified here.", "เอกสารหนึ่งหน้านี้แนะนำชุดสเปรดชีต SplitSuit ที่ให้กำหนดราคาเองผ่านหน้าเช็กเอาต์และมีคู่มือเริ่มต้น แต่ไม่ใช่ไฟล์ตาราง จึงตรวจสูตรหรือผลคำนวณจากเอกสารนี้ไม่ได้", "My Spreadsheets"),
],
"two-plus-two-nl-six-max": [
 ("Table and preflop positions", "เลือกโต๊ะและเล่นก่อนฟลอปตามตำแหน่ง", "Ryan Fee moves from table selection to UTG, middle position, cutoff, button, and blinds. The opening and isolation choices change with opponent looseness and stack depth; position is a central input.", "ไรอัน ฟีเริ่มจากการเลือกโต๊ะแล้วไล่ตำแหน่ง UTG ตำแหน่งกลาง คัตออฟ บัตตัน และบลายด์ การเปิดและไอโซเลตขึ้นกับความหลวมของคู่ต่อสู้และขนาดเงินกอง โดยตำแหน่งเป็นข้อมูลหลัก", "Preflop"),
 ("Three-bets and squeezes", "สามเบตและสควีซ", "The guide treats three-betting and squeezing as ways to attack opens and callers, especially in position, while considering who can continue and whether stacks permit later play.", "คู่มือใช้สามเบตและสควีซโจมตีคนเปิดกับคนคอล โดยเฉพาะเมื่อมีตำแหน่ง พร้อมพิจารณาว่าใครจะเล่นต่อและเงินกองพอสำหรับการเล่นสตรีตถัดไปหรือไม่", "Squeezing"),
 ("Flop decisions", "การตัดสินใจบนฟลอป", "Separate sections cover leading, continuation bets, check-raises, floats, value raises, bluffs, unraised pots, and wet versus dry boards. The reason for betting changes with opponent type and board texture.", "มีหัวข้อแยกเรื่องดองก์เบต ซีเบต เช็กเรส โฟลต เรสเพื่อมูลค่า บลัฟ พอตที่ไม่มีการเรส และ dry board หรือ wet board เหตุผลที่ลงเดิมพันเปลี่ยนตามคู่ต่อสู้และพื้นผิวบอร์ด", "Flop Play"),
 ("Turn and river", "เทิร์นและริเวอร์", "Turn material distinguishes double barrels, made-hand strength, position, check-raises, and floats. River material treats triple barrels, bluffs, and value raises; review the hand's full line before copying a bet size.", "เนื้อหาเทิร์นแยกการยิงสองสตรีต ความแข็งของไพ่ ตำแหน่ง เช็กเรส และโฟลต ส่วนริเวอร์ว่าด้วยยิงสามสตรีต บลัฟ และเรสเพื่อมูลค่า ควรทบทวนลำดับการเล่นทั้งมือก่อนนำขนาดเดิมพันไปใช้", "Turn Play"),
 ("Session management", "การดูแลเซสชัน", "Closing pages address mentality, health, upswings, session length, and multitabling as factors in decision quality.", "หน้าท้ายกล่าวถึงสภาพจิต สุขภาพ ช่วงชนะ ความยาวเซสชัน และการเล่นหลายโต๊ะซึ่งส่งผลต่อคุณภาพการตัดสินใจ", "Mentality"),
],
"strategies-beating-small-stakes-tournaments": [
 ("Opponent-first method", "เริ่มจากคู่ต่อสู้", "Jonathan Little argues against a fixed chart or one style for every small-stakes tournament. Observe actions even when out of the hand and adjust to the players present.", "โจนาธาน ลิตเติลคัดค้านการใช้ตารางไพ่หรือสไตล์เดียวกับทุกทัวร์นาเมนต์เดิมพันต่ำ ให้สังเกตการเล่นแม้ตนไม่ได้อยู่ในมือ แล้วปรับตามคนในโต๊ะ", "Focus on your opponents"),
 ("Loose-passive and loose-aggressive", "ผู้เล่นหลวมแบบรับและแบบบุก", "The book distinguishes opponents who enter too many pots and call too much from those who over-raise. Extract value from excessive calls; avoid confusing wide aggression with strong ranges.", "หนังสือแยกคนที่เข้าเล่นมากและคอลมากออกจากคนที่เรสบ่อยเกินไป ฝ่ายแรกเปิดทางให้เก็บมูลค่า ส่วนฝ่ายหลังต้องไม่ตีความการบุกกว้างว่าแข็งเสมอ", "Those who play too many hands"),
 ("Tight styles and sound opponents", "ผู้เล่นแน่นและผู้เล่นที่มีเหตุผล", "Players who enter too few hands can still differ sharply in passivity or aggression. The author also recognizes opponents playing roughly sound ranges, for whom crude population exploits need stronger evidence.", "ผู้เล่นที่เข้าเล่นน้อยยังต่างกันมากระหว่างสายรับกับสายบุก และมีผู้เล่นที่เลือกไพ่ค่อนข้างเหมาะสมด้วย การเอาจุดอ่อนของประชากรไปใช้กับคนกลุ่มหลังต้องมีหลักฐานชัดขึ้น", "Those who play too few hands"),
 ("Stack-sensitive examples", "ตัวอย่างที่ขึ้นกับเงินกอง", "The introduction contrasts deep-stack speculative hands with a 30bb stack, then shows how top pair can be a turn check against a tight range but a value bet against a loose caller. Treat its ROI claims as illustrative, not guarantees.", "บทนำเปรียบไพ่ลุ้นกำไรเมื่อกองลึกกับกอง 30bb และยกตัวอย่างท็อปแพร์ที่อาจเช็กเทิร์นต่อคนแน่น แต่เบตเก็บมูลค่าต่อคนคอลกว้าง ตัวเลขผลตอบแทนเป็นตัวอย่าง ไม่ใช่การรับประกัน", "Specific tendencies"),
],
"cash-game-killer": [
 ("Rules and bankroll", "กติกาและเงินทุน", "The early chapters teach hold'em streets and initial site/bankroll choices. Site references and income claims are historical; verify current conditions elsewhere.", "บทต้นอธิบายลำดับสตรีตของโฮลเอ็มและการเลือกเว็บไซต์กับเงินทุนเริ่มต้น ชื่อเว็บและข้อกล่าวอ้างเรื่องรายได้เป็นข้อมูลตามยุค ต้องตรวจสภาพปัจจุบันแยกต่างหาก", "Rules of Texas Holdem"),
 ("Preflop and TAG baseline", "ก่อนฟลอปและพื้นฐานเล่นแน่นบุก", "Starting hands, position, raises, flop play, and continuation bets form the book's tight-aggressive baseline; ask which worse hands call and which better hands fold.", "ไพ่เริ่มต้น ตำแหน่ง การเรส การเล่นฟลอป และซีเบตประกอบเป็นพื้นฐานแบบแน่นบุก ควรถามว่ามือแย่กว่าใดจะคอลและมือดีกว่าใดจะหมอบ", "Preflop Strategy"),
 ("Draws and made hands", "ไพ่รอและไพ่สำเร็จ", "The draw chapter separates pot odds, implied odds, and reverse implied odds; the next contrasts slowplaying and fast playing across pairs, two pair, straights, flushes, and stronger hands.", "บทไพ่รอแยกพอตออดส์ อิมพลายด์ออดส์ และรีเวิร์สอิมพลายด์ออดส์ จากนั้นเทียบการดักกับการเล่นเร็วเมื่อถือคู่ สองคู่ สเตรต ฟลัช และไพ่ใหญ่กว่า", "Playing Your Draws"),
 ("Opponent adaptation and advanced tools", "ปรับตามคู่ต่อสู้และเครื่องมือขั้นสูง", "Later chapters distinguish loose-passive players and rocks, then discuss board texture, image, semi-bluffs, a four-step read, floats, scare cards, notes, and table choice.", "บทท้ายแยกผู้เล่นหลวมรับกับสายแน่นจัด แล้วว่าด้วยพื้นผิวบอร์ด ภาพลักษณ์ เซมิบลัฟ การอ่านมือสี่ขั้น โฟลต ไพ่ที่ทำให้กลัว การจดโน้ต และเลือกโต๊ะ", "Advanced Strategy"),
 ("Practice aids", "เครื่องมือฝึก", "The closing section covers patience, tilt, goals, ongoing study, a glossary, odds chart, and starting-hand charts. Charts are aids, not replacements for opponent and stack context.", "ส่วนท้ายว่าด้วยความอดทน ทิลต์ เป้าหมาย การศึกษาต่อ อภิธานศัพท์ ตารางออดส์ และตารางไพ่เริ่มต้น ตารางเป็นเครื่องช่วย ไม่ใช่ตัวแทนข้อมูลคู่ต่อสู้และเงินกอง", "Closing Thoughts"),
],
"play-optimal-poker": [
 ("Equilibrium foundations", "พื้นฐานดุลยภาพ", "Andrew Brokos defines strategies, expected value, Nash equilibrium, indifference, and why genuine randomization is difficult for humans; the toy scenarios train these ideas before poker applications.", "แอนดรูว์ โบรคอสอธิบายกลยุทธ์ ค่าคาดหวัง ดุลยภาพแนช ความไม่เอนเอียงระหว่างตัวเลือก และเหตุที่มนุษย์สุ่มได้ไม่ดี เกมตัวอย่างใช้ฝึกแนวคิดก่อนนำไปใช้กับโป๊กเกอร์", "Chapter 1: Understanding Equilibrium"),
 ("Polarized and condensed ranges", "ช่วงไพ่ขั้วกับช่วงไพ่รวมตัว", "The Clairvoyance Game shows how strong hands plus bluffs interact with bluff-catchers and how indifference sets a defending frequency. The frequency belongs to the model's assumptions, not every live spot.", "เกม Clairvoyance แสดงการปะทะระหว่างไพ่แข็งรวมบลัฟกับไพ่จับบลัฟ และใช้ความไม่เอนเอียงกำหนดความถี่รับมือ ตัวเลขนั้นขึ้นกับสมมติฐานของเกม ไม่ใช่คำตอบทุกสถานการณ์จริง", "Chapter 2: Polarized Versus Condensed Ranges"),
 ("Reciprocal ranges and reality", "ช่วงไพ่ตอบโต้และการใช้จริง", "Half-street and full-street reciprocal-range games introduce sequential decisions; UTG versus BB then tests what changes when realistic positions and ranges replace tiny games.", "เกมช่วงไพ่ตอบโต้แบบครึ่งสตรีตและเต็มสตรีตสอนการตัดสินใจตามลำดับ แล้วตัวอย่าง UTG ปะทะ BB แสดงสิ่งที่เปลี่ยนเมื่อใช้ตำแหน่งและช่วงไพ่จริง", "Chapter 3: Reciprocal Ranges"),
 ("Exploitative process", "กระบวนการปรับหาจุดอ่อน", "The four-step process in chapter 5 starts from an equilibrium reference, identifies an opponent mistake, changes one's strategy to profit, and considers how the opponent may adjust back.", "กระบวนการสี่ขั้นในบทห้าเริ่มจากกลยุทธ์อ้างอิงแบบดุลยภาพ หาแนวโน้มผิดพลาดของคู่ต่อสู้ ปรับเพื่อเก็บกำไร และคิดว่าคู่ต่อสู้อาจปรับกลับอย่างไร", "Chapter 5: Crafting Exploitative Strategies"),
 ("Complex ranges, raising, synthesis", "ช่วงไพ่ซับซ้อน การเรส และสังเคราะห์", "The Ace-to-Five model adds more hand classes; raising introduces another strategic branch and blockers refine the final combined examples. Work the chapter tests against the original diagrams.", "เกม Ace-to-Five เพิ่มชนิดไพ่ การเรสเพิ่มทางเลือกเชิงกลยุทธ์ และบล็อกเกอร์ช่วยปรับตัวอย่างสรุปท้ายเล่ม ควรทำโจทย์เทียบแผนภาพต้นฉบับ", "Chapter 6: Complex Ranges"),
],
"super-system-1": [
 ("General poker strategy", "กลยุทธ์โป๊กเกอร์ทั่วไป", "Doyle Brunson frames poker as observation of people, with sections on tells, superstition, ethics, competitiveness, bankroll, courage, breaks, versatility, and tournaments.", "ดอยล์ บรันสันมองโป๊กเกอร์เป็นการสังเกตคน โดยมีหัวข้อเทล ความเชื่อ จริยธรรม ความมุ่งแข่งขัน เงินทุน ความกล้า การพัก ความยืดหยุ่น และทัวร์นาเมนต์", "Chapter One - General Poker Strategy"),
 ("Limit and no-limit", "ลิมิตกับโนลิมิต", "A bridge chapter compares betting structures. A tactic that is viable with capped raises need not carry over unchanged to uncapped no-limit bets.", "บทเชื่อมเปรียบเทียบโครงสร้างการเดิมพัน เทคนิคที่ใช้ได้เมื่อวงเงินเรสถูกจำกัดอาจใช้แบบเดิมไม่ได้ในโนลิมิต", "Similarities and Differences"),
 ("No-limit hand classes", "กลุ่มไพ่ในโนลิมิต", "The no-limit chapter treats antes, AA/KK, AK, queens, smaller pairs, connectors, marginal hands, trash, short-handed play, and insurance. It repeatedly connects preflop hand value to position, opponent, and postflop leverage.", "บทโนลิมิตครอบคลุมแอนตี AA/KK, AK, QQ คู่เล็ก ไพ่เรียง ไพ่ก้ำกึ่ง ไพ่แย่ การเล่นคนเหลือน้อย และประกัน โดยโยงค่าไพ่ก่อนฟลอปกับตำแหน่ง คู่ต่อสู้ และแรงกดดันหลังฟลอป", "Chapter Three - No Limit Hold'em"),
],
"peak-poker-performance": [
 ("Purpose, habits, and systems", "เป้าหมาย นิสัย และระบบ", "Cardner connects a clear reason to play with goals, small repeatable habits, daily plans, tracking, and implementation intentions. The activities ask the reader to turn vague ambition into observable routines.", "คาร์ดเนอร์เชื่อมเหตุผลที่เล่นกับเป้าหมาย นิสัยเล็กที่ทำซ้ำได้ แผนรายวัน การติดตามพฤติกรรม และแผนแบบถ้าเกิด X ให้ทำ Y กิจกรรมช่วยเปลี่ยนความตั้งใจลอย ๆ ให้เป็นกิจวัตรที่สังเกตได้", "What’s Your Why?"),
 ("A-game and attention", "เกมที่ดีที่สุดและการจดจ่อ", "The A-game chapter defines one's strongest performance, flow, situational awareness, pregame preparation, and responses to strong emotion; multitasking is treated as a cost to focus.", "บท A-game ให้ระบุลักษณะการเล่นที่ดีที่สุด ภาวะลื่นไหล การรู้สถานการณ์ การเตรียมก่อนเล่น และวิธีตอบสนองอารมณ์แรง ๆ โดยมองการทำหลายอย่างพร้อมกันว่าลดสมาธิ", "Deconstructing the A Game"),
 ("Psychological hurdles", "อุปสรรคทางจิตใจ", "The book traces tilt and other leaks through emotional awareness and learned responses, then offers exercises to name triggers and interrupt unhelpful thought patterns.", "หนังสือสืบที่มาของทิลต์และจุดรั่วอื่นผ่านการรู้เท่าทันอารมณ์กับปฏิกิริยาที่เรียนรู้มา พร้อมแบบฝึกระบุตัวกระตุ้นและหยุดแบบคิดที่ไม่ช่วย", "Common Psychological Hurdles"),
 ("Read as workbook", "ใช้เป็นสมุดฝึก", "Chapter highlights, observation activities, and Jonathan Little's comments are part of the instructional design; record an action and review it rather than reading as inspirational prose alone.", "สรุปบท กิจกรรมสังเกต และความเห็นของโจนาธาน ลิตเติลเป็นส่วนหนึ่งของการเรียน ควรจดการกระทำและทบทวนผล แทนที่จะอ่านเป็นคำปลุกใจอย่างเดียว", "Chapter Highlights"),
],
"hole-card-confessions": [
 ("Information and player types", "ข้อมูลและชนิดผู้เล่น", "Owen Gaines treats hands as an information contest: collect actions, infer why someone plays, then classify tendencies without claiming to know exact hole cards.", "โอเวน เกนส์มองมือโป๊กเกอร์เป็นการแข่งขันด้านข้อมูล: เก็บการกระทำ คาดเหตุผลที่คู่ต่อสู้เล่น แล้วจัดกลุ่มแนวโน้มโดยไม่อ้างว่ารู้ไพ่จริง", "Information"),
 ("Range construction and notes", "สร้างช่วงไพ่และจดโน้ต", "The range chapter builds and reshapes plausible hand sets; Eagle Eyes turns specific observations and notes into later decisions instead of broad labels alone.", "บทช่วงไพ่สร้างและปรับชุดไพ่ที่เป็นไปได้ ส่วน Eagle Eyes เปลี่ยนสิ่งที่สังเกตและจดเฉพาะเจาะจงให้ใช้ตัดสินใจครั้งต่อไป แทนการติดป้ายกว้าง ๆ", "Eagle Eyes"),
 ("Steal equity and range exploitation", "แย่งพอตและหาจุดอ่อนของช่วงไพ่", "Enter Steal Equity discusses ways to win pots without showdown, including position and limps; Exploiting a Range uses accumulated actions to predict how the opponent responds to bets.", "Enter Steal Equity ว่าด้วยการชนะพอตก่อนโชว์ไพ่ รวมตำแหน่งและการลิมป์ ส่วน Exploiting a Range ใช้การกระทำที่สะสมมาคาดว่าคู่ต่อสู้จะตอบสนองต่อเบตอย่างไร", "Enter Steal Equity"),
 ("Advanced reading and field trip", "อ่านเกมขั้นสูงและตัวอย่างสนามจริง", "Later chapters cover thinking levels, implied odds, paying for information, unknowns, and aggression. A Field Trip applies the method to hands; quizzes and answers support self-checking.", "บทท้ายครอบคลุมระดับความคิด อิมพลายด์ออดส์ การจ่ายเพื่อข้อมูล ความไม่แน่ใจ และความก้าวร้าว A Field Trip ใช้วิธีนี้กับมือจริง ส่วนแบบทดสอบกับเฉลยช่วยตรวจตนเอง", "Advanced Concepts"),
],
"negreanu-holdem-wisdom": [
 ("Rookie leaks and losing patterns", "จุดรั่วมือใหม่และสาเหตุแพ้", "The opening tips separate excessive bluffing, impatience, ego, weak fundamentals, tough game choice, and tilt. Audit which decision repeats before attributing losses to bad luck.", "บทต้นแยกการบลัฟเกิน ใจร้อน อีโก้ พื้นฐานไม่แน่น เลือกเกมยาก และทิลต์ ก่อนโทษโชคควรหาว่าการตัดสินใจผิดใดเกิดซ้ำ", "Top Ten Rookie Mistakes"),
 ("Starting and positional choices", "การเลือกไพ่เริ่มต้นและตำแหน่ง", "Negreanu's short lessons build practical hold'em judgment from hand selection, position, stack, and what the table will pay off. Read the advice as situational, not a static chart.", "บทสั้นของเนเกรอานูสร้างวิจารณญาณโฮลเอ็มจากไพ่เริ่มต้น ตำแหน่ง เงินกอง และสิ่งที่โต๊ะยอมจ่าย ควรอ่านเป็นคำแนะนำตามสถานการณ์ ไม่ใช่ตารางตายตัว", "position"),
 ("Bet sizing and showing cards", "ขนาดเบตและการเปิดไพ่", "The early sequence asks when a small bet gains more than a large one and whether revealing a hand changes future expectations. Judge the information given away as well as the current pot.", "บทช่วงต้นถามว่าเมื่อใดเบตเล็กให้ผลดีกว่าเบตใหญ่ และการเปิดไพ่เปลี่ยนความคาดหมายในมือหน้าอย่างไร ต้องคิดข้อมูลที่เผยออกไปควบคู่กับพอตปัจจุบัน", "When Less is More"),
 ("Trouble hands and board risk", "ไพ่ปัญหาและความเสี่ยงบนบอร์ด", "The pocket-jacks, AK, trouble-hands, suited-card, and dangerous-flop lessons warn that a strong-looking preflop hand can become marginal against a narrow continuing range.", "บท JJ, AK, ไพ่ปัญหา ไพ่ดอกเดียวกัน และฟลอปอันตรายเตือนว่าไพ่ก่อนฟลอปที่ดูแข็งอาจกลายเป็นไพ่ก้ำกึ่งเมื่อเจอช่วงไพ่ที่เล่นต่อแคบ", "Pondering Pocket Jacks"),
 ("Short and large stacks", "เงินกองสั้นและใหญ่", "Tips 24–25 contrast limited maneuvering room with a short stack and the ability of a large stack to apply pressure; neither stack size alone turns a bad call into a good one.", "ข้อ 24–25 เปรียบทางเลือกที่จำกัดเมื่อกองสั้นกับแรงกดดันที่กองใหญ่สร้างได้ แต่ขนาดกองอย่างเดียวไม่ทำให้คอลที่ผิดกลายเป็นคอลดี", "Playing on a Short Stack"),
 ("Opponent reads and pot control", "อ่านคู่ต่อสู้และควบคุมพอต", "The collection emphasizes observing betting patterns, using position to gather information, and matching pot size to hand strength and opponent tendencies.", "ชุดบทความเน้นสังเกตรูปแบบเดิมพัน ใช้ตำแหน่งเก็บข้อมูล และปรับขนาดพอตให้เข้ากับความแข็งของมือกับนิสัยคู่ต่อสู้", "opponent"),
 ("Math, rake, and bankroll", "คณิตศาสตร์ เรค และเงินทุน", "Tips 38–41 pair house edge and bankroll management with conditional probability and pot odds. A favorable decision has variance; rake can erase small edges.", "ข้อ 38–41 เชื่อมข้อได้เปรียบของเจ้ามือและการจัดการเงินทุนกับความน่าจะเป็นมีเงื่อนไขและพอตออดส์ การตัดสินใจที่คุ้มยังผันผวน และเรคอาจกินความได้เปรียบเล็ก ๆ", "Bankroll Management"),
 ("Ethics and alternative formats", "จริยธรรมและรูปแบบอื่น", "The soft-play warning, home-tournament setup, heads-up, short-handed, and WSOP tips mix etiquette, format-specific strategy, and tournament culture. Identify which lesson is a rule, a norm, or an anecdote.", "บทเตือนการออมมือ การจัดแข่งที่บ้าน เฮดส์อัป โต๊ะคนน้อย และ WSOP ผสมมารยาท กลยุทธ์เฉพาะรูปแบบ และวัฒนธรรมแข่ง ต้องแยกว่าอะไรเป็นกฎ บรรทัดฐาน หรือเรื่องเล่า", "Soft Playing is Cheating"),
 ("Tournament and practical judgment", "ทัวร์นาเมนต์และการตัดสินใจจริง", "Where the lessons discuss tournaments, stack pressure and changing incentives matter. The front matter includes publisher promotions; treat those as ancillary material.", "เมื่อบทเรียนพูดถึงทัวร์นาเมนต์ แรงกดดันจากเงินกองและแรงจูงใจที่เปลี่ยนตามช่วงมีผล ส่วนหน้าโฆษณาสำนักพิมพ์เป็นส่วนประกอบ ไม่ใช่หลักกลยุทธ์", "tournament"),
],
"gto-crash-course": [
 ("Basic game theory and AKQ", "ทฤษฎีเกมพื้นฐานและเกม AKQ", "The first video sections explain equilibrium with a tiny ace-king-queen game, then show how a known deviation creates an exploit.", "ตอนวิดีโอแรกอธิบายดุลยภาพผ่านเกมเล็กที่มี A K Q แล้วแสดงว่าความเบี่ยงเบนที่รู้แน่เปิดทางให้ปรับเก็บกำไรอย่างไร", "The AKQ Game"),
 ("A–5 model and range building", "เกม A–5 และสร้างช่วงไพ่", "The expanded model has more hand classes, allowing value, bluff, and bluff-catcher interactions that a three-card game cannot show.", "เกมที่ขยายเป็น A–5 มีชนิดไพ่มากขึ้น จึงแสดงการปะทะของไพ่เก็บมูลค่า ไพ่บลัฟ และไพ่จับบลัฟได้มากกว่าเกมสามใบ", "The A-5 Game"),
 ("Raising and exploitation in A–5", "การเรสและหาจุดอ่อนในเกม A–5", "The later toy-game lessons add raising and revisit how a known opponent deviation changes optimal responses. A strategy is conditional on the model's available actions and payoffs.", "บทเกมจำลองช่วงท้ายเพิ่มการเรสและย้อนดูว่าคู่ต่อสู้ที่เบี่ยงจากแผนเปลี่ยนคำตอบอย่างไร กลยุทธ์ขึ้นกับทางเลือกและผลตอบแทนที่แบบจำลองกำหนด", "A-5 Game With Raising"),
 ("GTO+ and player models", "GTO+ และแบบจำลองผู้เล่น", "Final video notes move from hand-built games to software strategy construction and player modeling. Verify tree, ranges, and bet sizes before trusting a solver frequency.", "บันทึกวิดีโอตอนท้ายย้ายจากเกมที่สร้างด้วยมือไปสู่การตั้งกลยุทธ์ในโปรแกรมและจำลองผู้เล่น ต้องตรวจต้นไม้ ช่วงไพ่ และขนาดเบตก่อนเชื่อความถี่จากโซลเวอร์", "GTO+ Strategy Building"),
 ("Apply and verify", "นำไปใช้และตรวจสมมติฐาน", "This is a strategy-guide companion to videos, so diagrams, exercises, and exact numerical frequencies should be checked in the source page before operational use.", "เอกสารนี้เป็นคู่มือประกอบวิดีโอ จึงควรตรวจแผนภาพ แบบฝึก และความถี่ตัวเลขจากหน้าต้นฉบับก่อนใช้จริง", "GTO CRASH COURSE"),
],
"poker-face-of-wall-street": [
 ("Poker, risk, and markets", "โป๊กเกอร์ ความเสี่ยง และตลาด", "Aaron Brown uses poker as a lens for risk taking and trading: both reward sizing choices under uncertainty, but markets add institutions, leverage, and counterparties beyond a card table.", "แอรอน บราวน์ใช้โป๊กเกอร์เป็นมุมมองเรื่องความเสี่ยงกับการซื้อขาย: ทั้งคู่ต้องเลือกขนาดเดิมพันเมื่อไม่แน่นอน แต่ตลาดมีสถาบัน เลเวอเรจ และคู่สัญญาที่ต่างจากโต๊ะไพ่", "Poker Face"),
 ("Historical narratives", "เรื่องเล่าประวัติศาสตร์", "Chapters follow gamblers, trading pits, crashes, and changing attitudes to speculation. These are historical and financial context, not direct hand charts or current investment instructions.", "หลายบทติดตามนักพนัน ตลาดซื้อขาย วิกฤต และทัศนคติต่อการเก็งกำไร เป็นบริบทประวัติศาสตร์กับการเงิน ไม่ใช่ตารางไพ่หรือคำสั่งลงทุนปัจจุบัน", "CHAPTER 7"),
 ("Probability and judgment", "ความน่าจะเป็นและวิจารณญาณ", "Use the book to ask how incentives, hidden information, and survival shape decisions; keep its analogies separate from exact poker EV calculations.", "ใช้หนังสือตั้งคำถามว่าแรงจูงใจ ข้อมูลซ่อน และการอยู่รอดเปลี่ยนการตัดสินใจอย่างไร แต่แยกอุปมาเหล่านี้ออกจากการคำนวณ EV ของโป๊กเกอร์โดยตรง", "CHAPTER 1"),
],
"dn-workbook-9036": [
 ("MasterClass workbook context", "บริบทแบบฝึก MasterClass", "This PDF is a Daniel Negreanu Teaches Poker workbook, with biography, lesson notes, and spaces for reflection; it supports a course rather than replacing all video instruction.", "PDF นี้เป็นสมุดฝึก Daniel Negreanu Teaches Poker มีชีวประวัติ บันทึกบทเรียน และพื้นที่สะท้อนความคิด ใช้ประกอบคอร์ส ไม่ได้แทนคำสอนทั้งหมดในวิดีโอ", "MASTERCLASS"),
 ("Position, ranges, and board texture", "ตำแหน่ง ช่วงไพ่ และพื้นผิวบอร์ด", "Chapters 2–4 use position and observed action to narrow plausible ranges. Board texture changes which range has the advantage; the hand review asks for a reasoned estimate rather than a precise read.", "บท 2–4 ใช้ตำแหน่งกับการกระทำเพื่อจำกัดช่วงไพ่ที่เป็นไปได้ พื้นผิวบอร์ดเปลี่ยนว่าฝ่ายใดได้เปรียบ ส่วนทบทวนมือให้ประเมินอย่างมีเหตุผล ไม่อ้างว่าอ่านไพ่ได้แม่นยำ", "HAND RANGES AND BOARD TEXTURE"),
 ("Theory, c-bets, and three-bets", "ทฤษฎี ซีเบต และสามเบต", "Chapters 5–9 connect baseline game theory and pot odds with c-bet plans, check-raises, and three-bet construction. The appendices include example ranges; verify suits visually.", "บท 5–9 เชื่อมทฤษฎีเกมพื้นฐานกับพอตออดส์ แผนซีเบต เช็กเรส และการสร้างช่วงสามเบต ภาคผนวกมีตัวอย่างช่วงไพ่ ต้องตรวจดอกจาก PDF ที่เห็นภาพ", "GAME THEORY AND MATH"),
 ("Bluffing and sizing", "บลัฟและขนาดเดิมพัน", "Chapters 10–16 cover coherent bluff lines, hand reviews, value/bluff sizing, overbets, multiway dynamics, and mixed actions. A bluff should tell a credible range story; an overbet needs a suitable range advantage.", "บท 10–16 ว่าด้วยลำดับบลัฟที่สมเหตุผล ทบทวนมือ ขนาดเบตเก็บมูลค่า/บลัฟ โอเวอร์เบต พอตหลายคน และการกระทำผสม บลัฟควรเล่าเรื่องช่วงไพ่ที่น่าเชื่อ และโอเวอร์เบตต้องมีเงื่อนไขช่วงไพ่ที่เหมาะ", "DETECTING AND EXECUTING THE BLUFF"),
 ("Tournament stack stages", "ช่วงเงินกองทัวร์นาเมนต์", "Chapters 18–21 distinguish early/middle play, bubble pressure, late/final-table incentives, and fold equity. Reassess the effective stack and payout pressure rather than replaying one default line.", "บท 18–21 แยกช่วงต้น/กลาง แรงกดดันบับเบิล ช่วงท้าย/โต๊ะสุดท้าย และโฟลด์อิควิตี ต้องประเมินเงินกองที่มีผลกับแรงกดดันเงินรางวัลใหม่ ไม่ใช้แผนเดิมซ้ำ", "TOURNAMENT STRATEGY"),
 ("Cash, tells, table talk, tilt", "เกมเงินสด เทล การพูด และทิลต์", "Chapters 22–29 move to cash-game value and deep stacks, masking/spotting physical tells, table talk, ordered thinking, and tilt management. Tells are deviations from a person's baseline, not universal gestures.", "บท 22–29 เปลี่ยนสู่การเก็บมูลค่าในเกมเงินสดและเงินกองลึก การซ่อน/สังเกตเทล การพูดที่โต๊ะ การคิดตามลำดับ และจัดการทิลต์ เทลควรดูความเบี่ยงจากนิสัยเดิมของคนนั้น ไม่ใช่ท่าทางสากล", "CASH GAMES"),
],
"crushing-the-microstakes": [
 ("Microstakes environment", "สภาพแวดล้อมไมโครสเตก", "Nathan Williams focuses on very small online NLHE cash games and player-pool tendencies. The preface stresses that advice from higher limits may not transfer unchanged.", "นาธาน วิลเลียมส์เน้นเกมเงินสด NLHE ออนไลน์ระดับเล็กมากกับแนวโน้มของผู้เล่น บทนำย้ำว่าคำแนะนำจากสเตกสูงอาจใช้ตรง ๆ ไม่ได้", "Introduction"),
 ("Preflop, value, and weak players", "ก่อนฟลอป เก็บมูลค่า และผู้เล่นอ่อน", "The core approach is disciplined starting-hand selection, position, clear value bets against callers, and attention to who actually folds. Judge a bluff against the particular opponent.", "แกนหลักคือเลือกไพ่เริ่มต้นอย่างมีวินัย ใช้ตำแหน่ง เบตเก็บมูลค่าให้ชัดต่อคนคอล และดูว่าใครหมอบจริง ก่อนบลัฟให้ประเมินคู่ต่อสู้รายนั้น", "Starting Hands"),
 ("HUD, table choice, and review", "สถิติประกอบ เลือกโต๊ะ และทบทวน", "The book uses online statistics, game selection, and hand review to identify recurring leaks. Historical software or site details should be checked against the current environment.", "หนังสือใช้สถิติออนไลน์ การเลือกเกม และการทบทวนมือเพื่อหาจุดรั่วซ้ำ ๆ รายละเอียดโปรแกรมหรือเว็บตามยุคควรตรวจใหม่", "Table Selection"),
],
"pot-limit-omaha-jeff-hwang": [
 ("Big-play PLO foundations", "พื้นฐาน PLO แบบมองพอตใหญ่", "Jeff Hwang introduces four-card PLO with the exact-two-hole-card rule, draw quality, nut potential, and the danger of attractive but dominated holdings.", "เจฟฟ์ ฮวางเริ่ม PLO สี่ใบด้วยกฎใช้ไพ่ในมือสองใบพอดี คุณภาพไพ่รอ โอกาสได้ไพ่ดีที่สุด และอันตรายของไพ่ที่ดูดีแต่แพ้ไพ่ชุดที่เหนือกว่า", "Basic Play and Key Concepts"),
 ("Straight draws and preflop", "ไพ่รอสเตรตและก่อนฟลอป", "Wraps can have many outs, but redraws and blockers matter. Starting-hand structure, connectedness, suits, and position affect whether a hand can make the nuts.", "แรปมีเอาต์จำนวนมากได้ แต่ต้องคิดไพ่รอต่อและบล็อกเกอร์ โครงสร้างไพ่เริ่มต้น ความต่อเนื่องของหน้าไพ่ ดอก และตำแหน่งกำหนดโอกาสทำไพ่ดีที่สุด", "The Straight Draws"),
 ("Flop decisions and quizzes", "ตัดสินใจหลังฟลอปและแบบทดสอบ", "After-flop and practice-hand sections distinguish made hands, draws, and pot-size commitments. Use the situation quizzes to test the reasoning, not merely memorize outcomes.", "บทหลังฟลอปกับตัวอย่างมือแยกไพ่สำเร็จ ไพ่รอ และการผูกมัดกับพอต ใช้แบบทดสอบสถานการณ์ตรวจเหตุผล ไม่ใช่จำผลลัพธ์", "After the Flop"),
 ("Omaha eight-or-better", "โอมาฮาไฮโล", "The latter large section switches to limit and pot-limit Omaha eight-or-better. High and low halves, qualifying lows, counterfeit risk, and scoop potential require a different model from high-only PLO.", "ส่วนท้ายขนาดใหญ่เปลี่ยนไปสู่ Omaha eight-or-better ทั้งลิมิตและพอตลิมิต ต้องคิดส่วนแบ่งไฮกับโล ไพ่โลที่ผ่านเกณฑ์ การถูกลบค่าหน้าไพ่ และโอกาสกวาดทั้งพอต ซึ่งต่างจาก PLO ไฮอย่างเดียว", "Limit Omaha Hi/Lo Split"),
],
"micro-stakes-playbook-9049": [
 ("Opponent taxonomy and preflop", "จัดกลุ่มคู่ต่อสู้และก่อนฟลอป", "Williams distinguishes bad and good regulars from whales and maniacs, then builds opening, stealing, three-bet defense, and four-bet plans around who is in the pot.", "วิลเลียมส์แยกเร็กอ่อน เร็กเก่ง ผู้เล่นที่คอลมาก และสายบุกมั่ว แล้วสร้างแผนเปิด แย่งบลายด์ รับมือสามเบต และสี่เบตตามคนในพอต", "The Preflop Strategy Playbook"),
 ("Flop and turn pressure", "แรงกดดันบนฟลอปกับเทิร์น", "Flop chapters cover c-bets, floats, raises, and three-bet pots. Turn chapters add second barrels, double floats, and bluff raises; choose candidates using range and opponent evidence.", "บทฟลอปว่าด้วยซีเบต โฟลต เรส และพอตสามเบต บทเทิร์นเพิ่มยิงสตรีตสอง ดับเบิลโฟลต และเรสบลัฟ ต้องเลือกมือจากช่วงไพ่และหลักฐานคู่ต่อสู้", "The Flop Strategy Playbook"),
 ("River choices", "การตัดสินใจริเวอร์", "The river playbook separates triple barrels, stop-and-go value, thin raises, and bluff catches. The key comparison is worse hands that call versus better hands that remain.", "แผนริเวอร์แยกยิงสามสตรีต เบตเก็บมูลค่าแบบหยุดแล้วไป เรสบาง และคอลจับบลัฟ ต้องเทียบว่ามือแย่กว่าใดคอลกับมือดีกว่าใดยังอยู่", "The River Strategy Playbook"),
 ("Stop-and-go bluff and river raise", "บลัฟแบบหยุดแล้วไปและเรสริเวอร์", "Chapters 14–15 add a delayed bluff and river bluff raise. These depend on a credible prior line and an opponent able to fold; the dramatic chapter labels are not evidence of automatic profit.", "บท 14–15 เพิ่มบลัฟช้าหลังเช็กและเรสบลัฟริเวอร์ ต้องมีลำดับก่อนหน้าที่น่าเชื่อและคู่ต่อสู้ที่หมอบได้ ชื่อบทที่แรงไม่ใช่หลักฐานว่าทำแล้วกำไรแน่", "The Stop and Go Bluff"),
 ("Professional routine", "กิจวัตรผู้เล่นจริงจัง", "Final chapters cover study, leak fixing, HUD setup, table selection, bankroll planning, variance, and tilt. These are process suggestions, not guaranteed income or current site guidance.", "บทท้ายครอบคลุมการเรียน การอุดจุดรั่ว การตั้ง HUD การเลือกโต๊ะ แผนเงินทุน ความผันผวน และทิลต์ เป็นคำแนะนำกระบวนการ ไม่ใช่การรับประกันรายได้หรือคู่มือเว็บไซต์ปัจจุบัน", "The Professional Poker Playbook"),
],
"super-system-2": [
 ("History, online play, and specialization", "ประวัติ เกมออนไลน์ และความชำนาญเฉพาะทาง", "Brunson's story, no-limit history, online play, and the specialization discussion provide context before the variant chapters. Treat online-room promotions as archival.", "เรื่องชีวิตบรันสัน ประวัติโนลิมิต เกมออนไลน์ และการเลือกความชำนาญให้บริบทก่อนเข้าสู่แต่ละเกม ส่วนโฆษณาห้องโป๊กเกอร์ออนไลน์เป็นข้อมูลเก่า", "The History of No Limit"),
 ("Limit hold'em", "โฮลเอ็มแบบลิมิต", "The limit chapter requires fixed-bet pot odds, starting-hand selection, and thin value decisions. Its bet structure changes bluff leverage compared with no-limit.", "บทลิมิตต้องคิดพอตออดส์จากวงเงินเดิมพันตายตัว เลือกไพ่เริ่มต้น และเก็บมูลค่าแบบบาง ๆ โครงสร้างเบตทำให้แรงบลัฟต่างจากโนลิมิต", "Limit Hold'em Poker"),
 ("Omaha eight-or-better", "โอมาฮาไฮโล", "The high-low chapter concerns qualifying lows, split-pot economics, scoop hands, and avoiding quartered outcomes; do not import hold'em hand rankings unchanged.", "บทไฮโลว่าด้วยเงื่อนไขไพ่โล การแบ่งพอต มือที่กวาดทั้งพอต และการหลีกเลี่ยงรับเพียงหนึ่งในสี่ อย่านำการจัดอันดับไพ่โฮลเอ็มมาใช้ตรง ๆ", "Omaha Eight or Better"),
 ("Seven-card stud eight-or-better", "เซเวนการ์ดสตัดไฮโล", "Todd Brunson's separate stud high-low chapter starts with exposed-card and live-card decisions. Use its stud betting rounds and split-pot rules, rather than Omaha's four-hole-card model.", "บทสตัดไฮโลแยกของท็อดด์ บรันสันเริ่มจากการอ่านไพ่หงายและไพ่ที่ยังเหลือในสำรับ ต้องใช้ลำดับเดิมพันกับกติกาแบ่งพอตของสตัด ไม่ใช่รูปแบบไพ่ในมือสี่ใบของโอมาฮา", "SEVEN CARD STUD HIGH LOW EIGHT-OR-BETTER"),
 ("Pot-limit Omaha high", "พอตลิมิตโอมาฮาไฮ", "PLO high emphasizes starting-hand coordination, nut draws, position, and pot-limit sizing. Draw equity can dominate single made pairs.", "PLO ไฮเน้นไพ่เริ่มต้นที่ประสานกัน ไพ่รอแนต ตำแหน่ง และขนาดเบตตามพอต ไพ่รอที่ดีอาจมีอิควิตีเหนือคู่ที่สำเร็จแล้ว", "Pot Limit Omaha High"),
 ("Triple draw and tournaments", "ทริปเปิลดรอว์และทัวร์นาเมนต์", "The triple-draw chapter is a different lowball game with drawing rounds and hand-selection rules. Tournament overview and no-limit hold'em then return to stack pressure, opponent reading, and aggression.", "บททริปเปิลดรอว์เป็นเกมโลว์บอลอีกชนิด มีรอบเปลี่ยนไพ่และกฎเลือกมือเฉพาะ จากนั้นภาพรวมทัวร์นาเมนต์กับโนลิมิตโฮลเอ็มกลับมาที่แรงกดดันเงินกอง การอ่านคน และการบุก", "Triple Draw Poker"),
 ("Tournament overview and no-limit hold'em", "ภาพรวมทัวร์นาเมนต์และโนลิมิตโฮลเอ็ม", "The tournament overview is a distinct section before Brunson's revised no-limit hold'em chapter. The latter discusses starting hands, aggression, and reading people under uncapped betting; it is not interchangeable with Jennifer Harman's limit chapter.", "ภาพรวมทัวร์นาเมนต์เป็นส่วนแยกก่อนบทโนลิมิตโฮลเอ็มฉบับปรับปรุงของบรันสัน ซึ่งว่าด้วยไพ่เริ่มต้น การบุก และการอ่านคนภายใต้เบตไม่จำกัด ต่างจากบทลิมิตของเจนนิเฟอร์ ฮาร์แมน", "No Limit Hold'em"),
 ("WPT history and glossary", "ประวัติ WPT และอภิธานศัพท์", "The World Poker Tour section describes televised poker's growth and tournament setting; the end glossary is a reference for terms, not a new strategy chapter.", "ส่วน World Poker Tour เล่าการเติบโตของโป๊กเกอร์ถ่ายทอดสดและบรรยากาศทัวร์นาเมนต์ ส่วนอภิธานศัพท์ท้ายเล่มใช้เปิดคำศัพท์ ไม่ใช่บทกลยุทธ์ใหม่", "World Poker Tour"),
],
"gripsed-mtt-strategy-guide": [
 ("Preparation", "เตรียมก่อนแข่ง", "The pre-game chapter covers study environment, registration choices, and readiness so decisions begin before the first hand.", "บทก่อนแข่งครอบคลุมสภาพแวดล้อมเรียน การเลือกลงทะเบียน และความพร้อม เพื่อให้การตัดสินใจเริ่มก่อนแจกมือแรก", "PRE-GAME STRATEGY"),
 ("Early, middle, late stages", "ช่วงต้น กลาง และท้าย", "The guide changes priorities as blinds grow and effective stacks shrink: early preservation and information gathering, middle-stage steals and pressure, and late-stage survival versus accumulation.", "คู่มือปรับเป้าหมายเมื่อบลายด์โตและเงินกองที่มีผลลดลง ช่วงต้นรักษาชิปและเก็บข้อมูล ช่วงกลางหาจังหวะแย่งพอต ช่วงท้ายชั่งการอยู่รอดกับการสะสมชิป", "EARLY STAGE STRATEGY"),
 ("Defense and offense", "ตั้งรับและบุก", "The final chapter frames initiative, defending blinds, and counterattacks by stack size and opponents, rather than treating aggression as a goal itself.", "บทสุดท้ายมองการเป็นฝ่ายเริ่ม การป้องกันบลายด์ และการสวนกลับผ่านเงินกองกับคู่ต่อสู้ ไม่ได้มองการบุกเป็นเป้าหมายในตัว", "DEFENCE"),
],
"the-theory-of-poker": [
 ("Expectation and structure", "ค่าคาดหวังและโครงสร้างเกม", "Sklansky starts with EV/hourly rate, antes, odds, and the effect of many opponents. The book spans poker forms; verify each example's game and bet structure before applying it to NLHE.", "สแคลนสกีเริ่มจากค่าคาดหวัง ผลตอบแทนต่อชั่วโมง แอนตี ออดส์ และผลของหลายคู่ต่อสู้ หนังสือครอบคลุมโป๊กเกอร์หลายชนิด จึงต้องตรวจชนิดเกมกับกติกาเดิมพันก่อนนำตัวอย่างไปใช้ใน NLHE", "Expectation and Hourly Rate"),
 ("Odds and deception", "ออดส์และการพรางมือ", "Effective and implied odds account for future streets; reverse implied losses arise when a draw makes a second-best hand. Deception's value depends on what opponents can notice and adjust to.", "ออดส์ที่มีผลจริงกับอิมพลายด์ออดส์รวมสตรีตหน้า ส่วนการเสียเพิ่มเมื่อไพ่รอเข้าแต่แพ้ไพ่ใหญ่กว่าคือความเสี่ยงอีกด้าน คุณค่าของการพรางมือขึ้นกับสิ่งที่คู่ต่อสู้สังเกตและปรับได้", "Effective Odds"),
 ("Fundamental theorem and big pots", "หลักทฤษฎีและพอตใหญ่", "The core idea compares an opponent's action with what they would do if they saw your cards; large pots amplify the cost of a wrong fold or call. Multiway pots complicate that simple comparison.", "แกนทฤษฎีเทียบการกระทำของคู่ต่อสู้กับสิ่งที่เขาจะทำหากเห็นไพ่เรา พอตใหญ่ทำให้การหมอบหรือคอลผิดมีต้นทุนสูงขึ้น แต่พอตหลายคนทำให้การเทียบแบบง่ายซับซ้อนขึ้น", "Win the Big Pots Right Away"),
 ("Semi-bluff, raising, check-raising, slowplay", "เซมิบลัฟ เรส เช็กเรส และดัก", "Later chapters distinguish a bluff with drawing equity from pure bluff, list multiple purposes of a raise, specify conditions for check-raising, and explain when slowplay sacrifices less value than it gains.", "บทหลังแยกบลัฟที่ยังมีโอกาสเข้าไพ่ออกจากบลัฟล้วน แจกเหตุผลหลายอย่างของการเรส ระบุเงื่อนไขเช็กเรส และอธิบายเมื่อใดการดักคุ้มกับมูลค่าที่เสียไป", "Check-Raising"),
 ("Loose and tight games", "เกมหลวมกับเกมแน่น", "Strategy changes with field looseness: the chance of getting called alters semibluff value, while legitimate made hands can gain value in loose games.", "กลยุทธ์เปลี่ยนตามความหลวมของโต๊ะ โอกาสถูกคอลเปลี่ยนค่าของเซมิบลัฟ ส่วนไพ่สำเร็จแข็งมักเก็บมูลค่าได้มากขึ้นในเกมหลวม", "Loose and Tight Play"),
],
"mental-game-of-poker": [
 ("Learning model and tilt", "แบบจำลองการเรียนรู้และทิลต์", "Jared Tendler treats emotional reactions as signals of underlying thinking errors, then uses a learning process and written profiles to diagnose recurring tilt, rather than merely telling players to calm down.", "จาเร็ด เทนด์เลอร์มองปฏิกิริยาอารมณ์เป็นสัญญาณของความคิดที่ผิดพลาดอยู่ใต้ผิว แล้วใช้กระบวนการเรียนกับโปรไฟล์ที่เขียนไว้เพื่อหาสาเหตุทิลต์ซ้ำ", "TILT"),
 ("Recognizable tilt forms", "รูปแบบทิลต์ที่แยกได้", "The text separates injustice, revenge, entitlement, and other triggers; each needs a different correction because the belief driving it differs.", "หนังสือแยกทิลต์จากความรู้สึกไม่ยุติธรรม การเอาคืน ความรู้สึกว่าตนควรได้ และตัวกระตุ้นอื่น แต่ละชนิดต้องแก้ต่างกันเพราะความเชื่อที่อยู่เบื้องหลังต่างกัน", "INJUSTICE"),
 ("Confidence, motivation, focus", "ความมั่นใจ แรงจูงใจ และสมาธิ", "Later material connects variance and results to unstable confidence, motivation, and focus. Use session notes to distinguish poor decisions from unlucky outcomes.", "ส่วนหลังโยงความผันผวนและผลลัพธ์กับความมั่นใจ แรงจูงใจ และสมาธิที่ไม่นิ่ง ใช้บันทึกเซสชันแยกการตัดสินใจแย่จากผลที่โชคร้าย", "CONFIDENCE"),
],
"poker-math-preflop-workbook": [
 ("Equity and range counting", "อิควิตีและการนับช่วงไพ่", "The workbook begins with equity setups, range building, combinations, and blockers. Write the assumed ranges before calculating; a precise number from the wrong range is unhelpful.", "สมุดฝึกเริ่มจากการตั้งโจทย์อิควิตี สร้างช่วงไพ่ นับคอมโบ และบล็อกเกอร์ ต้องเขียนสมมติฐานช่วงไพ่ก่อนคำนวณ เพราะตัวเลขแม่นจากช่วงไพ่ผิดก็ไม่มีประโยชน์", "Equity Setups"),
 ("Pot odds and EV", "พอตออดส์และค่าคาดหวัง", "Middle exercises cover pot odds, implied odds, breakeven percentages, auto-profit, and EV. Keep immediate odds distinct from money that may be won or lost later.", "โจทย์กลางเล่มว่าด้วยพอตออดส์ อิมพลายด์ออดส์ จุดคุ้มทุน กำไรอัตโนมัติ และ EV ต้องแยกออดส์ที่เห็นตอนนี้จากเงินที่จะได้หรือเสียในสตรีตหน้า", "Pot Odds"),
 ("Preflop applications", "ประยุกต์ก่อนฟลอป", "The final problem sets apply the math to opening, isolation, three-bets, squeezes, four-bets, and preflop all-ins. Challenge mode and major takeaways are review aids.", "ชุดโจทย์ท้ายใช้คณิตศาสตร์กับการเปิด ไอโซเลต สามเบต สควีซ สี่เบต และออลอินก่อนฟลอป โหมดท้าทายกับสรุปหลักใช้ทบทวน", "Open-Raising"),
 ("Answer-key limitation", "ข้อจำกัดเรื่องเฉลย", "A separate one-page file points to answer-key versions; it is not the full key in this archive. Check actual calculations rather than assuming the referenced external asset is present.", "ไฟล์แยกหนึ่งหน้าชี้ไปยังฉบับเฉลย แต่คลังนี้ไม่มีตัวเฉลยเต็ม ควรตรวจการคำนวณจริง ไม่สมมติว่ามีทรัพยากรภายนอกอยู่ใน ZIP", "Answer Key"),
],
"winning-secrets-online-poker": [
 ("Online setup and game formats", "เริ่มเล่นออนไลน์และชนิดเกม", "The Fryes cover account setup, online mechanics, game variants, and cash versus tournament structure. Site and security advice dates from 2005 and needs present-day verification.", "ตระกูลฟรายอธิบายการเริ่มบัญชี กลไกออนไลน์ เกมหลายแบบ และความต่างเกมเงินสดกับทัวร์นาเมนต์ คำแนะนำเรื่องเว็บกับความปลอดภัยมาจากปี 2005 ต้องตรวจปัจจุบัน", "Getting Started"),
 ("Hand play by street", "เล่นมือตามสตรีต", "Chapters on starting hands, flop/fourth street, turn/fifth and sixth streets, and river follow both hold'em and other variants. Keep the street terminology tied to its game.", "บทไพ่เริ่มต้น ฟลอปหรือสตรีตสี่ เทิร์นหรือสตรีตห้าหก และริเวอร์ครอบคลุมทั้งโฮลเอ็มและเกมอื่น ต้องอ่านชื่อสตรีตให้ตรงชนิดเกม", "Starting Hands"),
 ("Analysis and discipline", "วิเคราะห์และรักษาวินัย", "The later chapters use spreadsheets and poker software to evaluate results, then discuss turning data into behavioral discipline and a stable playing environment.", "บทท้ายใช้สเปรดชีตและโปรแกรมโป๊กเกอร์วิเคราะห์ผลงาน แล้วอธิบายการแปลงข้อมูลเป็นวินัยกับการจัดสภาพแวดล้อมเล่นให้มั่นคง", "Evaluating Your Play Using Spreadsheets"),
 ("Cheating chapter", "บทเรื่องการโกง", "The dedicated cheating chapter is a historical account of online integrity risks; do not treat it as a complete current threat model.", "บทการโกงเป็นภาพความเสี่ยงด้านความซื่อตรงออนไลน์ตามยุค ไม่ใช่รายการภัยคุกคามปัจจุบันที่ครบถ้วน", "Cheating"),
],
"decide-to-play-great-poker": [
 ("Decision framework and position", "กรอบการตัดสินใจและตำแหน่ง", "Annie Duke begins with deliberate decisions, position, raising, and playing ranges rather than becoming attached to one's own cards.", "แอนนี ดุ๊กเริ่มจากการตัดสินใจอย่างมีเหตุผล ตำแหน่ง การเรส และการคิดเป็นช่วงไพ่แทนการยึดติดกับไพ่ตนเอง", "Decide to Decide"),
 ("Bluffs, adjustments, and raises", "บลัฟ ปรับตัว และรับมือเรส", "The middle chapters distinguish bluff frequency and opponent adaptation, then ask how to respond when a prior plan meets a raise.", "บทกลางแยกความถี่บลัฟกับการปรับตามคู่ต่อสู้ แล้วถามว่าจะรับมืออย่างไรเมื่อแผนเดิมเจอการเรส", "The Art of Adjustment"),
 ("Flop texture and hand classes", "พื้นผิวฟลอปและชนิดไพ่", "Separate chapters analyze huge flops, bad position, multiway monsters, textured boards, draws, and top pair on dry versus textured boards. Relative strength matters more than hand name alone.", "บทแยกวิเคราะห์ฟลอปที่เข้าแรง ตำแหน่งเสีย พอตหลายคน wet board ไพ่รอ และท็อปแพร์บน dry board หรือ wet board ความแข็งสัมพัทธ์สำคัญกว่าชื่อมือ", "Flopping Huge"),
 ("River and management", "ริเวอร์และการจัดการ", "River chapters split in-position from out-of-position play; management closes with the practical context needed to keep making good decisions.", "บทริเวอร์แยกการเล่นเมื่อมีตำแหน่งกับเสียตำแหน่ง ส่วนบทจัดการปิดท้ายด้วยบริบทที่ช่วยรักษาคุณภาพการตัดสินใจ", "River Play In Position"),
],
"grinders-manual": [
 ("EV and opening", "EV และการเปิดพอต", "Peter Clarke frames EV as the measure of a decision and starts the six-max cash syllabus with hand ratings and position-aware opening.", "ปีเตอร์ คลาร์กใช้ EV วัดคุณภาพการตัดสินใจ และเริ่มหลักสูตรเกมเงินสดหกคนด้วยการประเมินไพ่กับการเปิดตามตำแหน่ง", "Opening the Pot"),
 ("Limpers, c-bets, value", "เจอลิมป์ ซีเบต และเก็บมูลค่า", "The ISO triangle combines frequent strength, fold equity, and position; later sections choose c-bet size and distinguish thick from thin value, including when not to slowplay.", "สามเหลี่ยมไอโซเลตประกอบด้วยโอกาสมีไพ่แข็ง โฟลด์อิควิตี และตำแหน่ง ต่อด้วยการเลือกขนาดซีเบตและแยกเบตมูลค่าหนา-บาง รวมถึงเมื่อไม่ควรดัก", "When Someone Limps"),
 ("Calling opens and facing bets", "คอลการเปิดและรับมือเบต", "The manual separates in-position and out-of-position calls, blind defense, end-of-action calls, and flop/turn decisions while action remains open.", "คู่มือแยกคอลเมื่อมีและเสียตำแหน่ง การป้องกันบลายด์ การคอลเมื่อการกระทำจบ และการตัดสินใจบนฟลอปหรือเทิร์นเมื่อยังมีคนเล่นต่อ", "Calling Opens"),
 ("Combinations and three-bets", "คอมโบและสามเบต", "Combinatorics and blockers refine range estimates. Three-bet chapters compare polarized and linear constructions, squeezing, sizing, defense, and counter-adjustment.", "การนับคอมโบกับบล็อกเกอร์ช่วยปรับประมาณช่วงไพ่ บทสามเบตเทียบช่วงไพ่แบบขั้วกับแบบเรียงแรง รวมสควีซ ขนาดเบต การป้องกัน และการปรับสวน", "Combos and Blockers"),
 ("Later streets and stack depth", "สตรีตหลังและความลึกเงินกอง", "Turn and river bluffing, delayed c-bets, probes, bluff raises, three-bet-pot balance, and deep/shallow stacks round out the syllabus. Appendices supply jargon and figure lists.", "การบลัฟเทิร์นริเวอร์ ซีเบตช้า โพรบ เรสบลัฟ สมดุลพอตสามเบต และเงินกองลึกหรือตื้นปิดหลักสูตร ภาคผนวกมีอภิธานศัพท์และรายการภาพ", "Bluffing the Turn and River"),
],
}

# Explicit primary chapter maps. Subtopics remain searchable in the page corpus;
# these maps keep the parent TOC sequence visible in either language.
OUTLINE = {
"pokercoaching-cash-game-cheat-sheet": [
 ("Cash fundamentals", "พื้นฐานเกมเงินสด", 1),
 ("Player-type adjustments", "ปรับตามชนิดผู้เล่น", 2),
 ("Cash-game checklist", "รายการทบทวนเกมเงินสด", 3),
 ("Visual hand rankings", "ลำดับไพ่แบบภาพ", 4),
 ("Additional resources", "แหล่งเรียนรู้เพิ่มเติม", 5),
],
"pokercoaching-tournament-cheat-sheet": [
 ("Tournament fundamentals", "พื้นฐานทัวร์นาเมนต์", 1),
 ("Exploits for common player types", "การปรับตามชนิดผู้เล่น", 2),
 ("Things to focus on", "สิ่งที่ควรใส่ใจ", 3),
 ("Visual hand rankings", "ลำดับไพ่แบบภาพ", 4),
 ("Additional resources", "แหล่งเรียนรู้เพิ่มเติม", 5),
],
"dn-workbook-9036": [
 ("Introduction", "1 บทนำ",3),
 ("Understanding Position", "2 เข้าใจตำแหน่ง",5),
 ("Hand Ranges and Board Texture", "3 ช่วงไพ่และพื้นผิวบอร์ด",10),
 ("Ranges: Hand Review", "4 ทบทวนมือเรื่องช่วงไพ่",15),
 ("Game Theory and Math", "5 ทฤษฎีเกมและคณิตศาสตร์",18),
 ("C-Betting", "6 ซีเบต",25),
 ("Check-Raising", "7 เช็กเรส",28),
 ("Three-Betting", "8 สามเบต",30),
 ("Three-Betting: Hand Review", "9 ทบทวนมือสามเบต",34),
 ("Detecting and Executing the Bluff", "10 ตรวจจับและลงมือบลัฟ",36),
 ("Executing the Bluff: Hand Reviews", "11 ทบทวนมือบลัฟ",41),
 ("Bet Sizing", "12 ขนาดเดิมพัน",45),
 ("Overbetting", "13 เบตเกินพอต",47),
 ("Multi-Way Dynamics", "14 พลวัตพอตหลายคน",50),
 ("Mixed Strategy", "15 กลยุทธ์ผสม",53),
 ("Mixed Strategy: Hand Review", "16 ทบทวนมือกลยุทธ์ผสม",58),
 ("Pre- and Postflop Mistakes", "17 ข้อผิดพลาดก่อนและหลังฟลอป",61),
 ("Tournament Strategy: Early and Middle Stages", "18 ทัวร์นาเมนต์ช่วงต้นและกลาง",64),
 ("Tournament Strategy: On the Bubble", "19 ทัวร์นาเมนต์ช่วงบับเบิล",68),
 ("Tournament Strategy: Late Stages and Final Table", "20 ทัวร์นาเมนต์ช่วงท้ายและโต๊ะสุดท้าย",70),
 ("Universal Tournament Strategy", "21 หลักทัวร์นาเมนต์ทั่วไป",73),
 ("Cash Games", "22 เกมเงินสด",76),
 ("Masking Tells", "23 ซ่อนเทลของตน",79),
 ("Spotting Tells, Part One", "24 สังเกตเทลภาคหนึ่ง",82),
 ("Spotting Tells, Part Two", "25 สังเกตเทลภาคสอง",85),
 ("Spotting Tells: Hand Reviews", "26 ทบทวนมือเรื่องเทล",88),
 ("Table Talk", "27 การพูดคุยที่โต๊ะ",91),
 ("How to Think at the Poker Table", "28 วิธีคิดที่โต๊ะ",95),
 ("Managing and Exploiting Tilt", "29 จัดการและใช้ทิลต์คู่ต่อสู้",97),
],
"micro-stakes-playbook-9049": [
 ("Introduction", "บทนำ"),
 ("1. How to Create Custom Opening Ranges", "1 สร้างช่วงไพ่เปิดเฉพาะโต๊ะ"),
 ("2. Picking up the Easy Money Before the Flop", "2 เก็บพอตง่ายก่อนฟลอป"),
 ("3. Crushing the Regs in 3Bet Pots", "3 เล่นกับเร็กในพอตสามเบต"),
 ("4. How to Defend Against 3Bets Effectively", "4 ป้องกันสามเบต"),
 ("5. How to Dominate 4Bet Pots", "5 พอตสี่เบต"),
 ("6. Floating Their CBets Like a Champion", "6 โฟลตซีเบต"),
 ("7. Raising Them All Day on the Flop", "7 เรสบนฟลอป"),
 ("8. The Subtle Art of Dominating 3Bet Pots on the Flop", "8 ฟลอปในพอตสามเบต"),
 ("9. Firing the Second Shell and Making Them Fold", "9 ยิงสตรีตสอง"),
 ("10. Double Floating - The Secret Weapon", "10 ดับเบิลโฟลต"),
 ("11. The Turn Bluff Raise: Owning Their Soul", "11 เรสบลัฟเทิร์น"),
 ("12. Triple Barreling - The Strongest Play in the Game", "12 ยิงสามสตรีต"),
 ("13. The Stop and Go Value Bet", "13 หยุดแล้วเบตเก็บมูลค่า"),
 ("14. The Stop and Go Bluff", "14 หยุดแล้วบลัฟ"),
 ("15. The River Bluff Raise", "15 เรสบลัฟริเวอร์"),
 ("16. The Thin River Value Raise", "16 เรสเก็บมูลค่าบางบนริเวอร์"),
 ("17. The Big Call - Neutralizing Their Aggression", "17 คอลใหญ่รับมือความก้าวร้าว"),
 ("18. How to Study Your Poker Game and Plug Your Leaks", "18 ศึกษาเกมและอุดจุดรั่ว"),
 ("19. Playing in the Right Poker Games - Finding the Fish", "19 เลือกเกมและหาคู่ต่อสู้ที่อ่อนกว่า"),
 ("20. Poker Finance - The Pro’s Edge", "20 การเงินสำหรับผู้เล่น"),
 ("21. The Mental Advantage - Unbreakable", "21 ความได้เปรียบทางจิตใจ"),
],
"crushing-the-microstakes": [
 ("Introduction", "บทนำ"), ("Variance", "ความผันผวน"),
 ("The Micros", "ลักษณะไมโครสเตก"), ("The Limits", "แยก NL2 กับ NL5"),
 ("Bankroll", "เงินทุน"), ("Tracking Software", "โปรแกรมเก็บสถิติ"),
 ("Player Types", "ชนิดผู้เล่น"), ("Table Selection", "เลือกโต๊ะ"),
 ("General Approach", "แนวทางทั่วไป"), ("Preflop", "ก่อนฟลอป"),
 ("Range by Position", "ช่วงไพ่ตามตำแหน่ง"), ("The Flop", "ฟลอป"),
 ("After the Cbet", "หลังซีเบต"), ("The Turn", "เทิร์น"),
 ("The River", "ริเวอร์"), ("The Heart of it All (Extraction)", "การเก็บมูลค่าหลัก"),
 ("Some General Rules", "กฎทั่วไป"), ("Final Thoughts", "ส่งท้าย"),
],
"strategies-beating-small-stakes-tournaments": [
 ("Introduction", "บทนำ"),
 ("Focus on your opponents", "สังเกตคู่ต่อสู้"),
 ("The three player types who play small stakes tournaments", "ผู้เล่นสามประเภทในทัวร์นาเมนต์เล็ก"),
 ("Those who play too many hands", "ผู้เล่นมือมากเกิน"),
 ("Those who play too few hands", "ผู้เล่นมือน้อยเกิน"),
 ("Those who play roughly the correct amount of hands in an intelligent manner", "ผู้เล่นที่เลือกมือสมเหตุผล"),
 ("Specific tendencies you will encounter in small stakes tournaments", "แนวโน้มเฉพาะที่พบในเกมเล็ก"),
 ("Conclusion", "สรุป"),
],
"thai-document-915850": [
 ("Short-stack cash-game approach", "เกมเงินสดโฮลเอ็มเงินกองสั้น",1),
 ("Short-stack play and starting hands", "วิธีเล่นและเลือกไพ่เงินกองสั้น",2),
 ("Bluffing with a short stack", "การบลัฟเมื่อเงินกองสั้น",3),
 ("Table selection and opponents", "การเลือกโต๊ะและคู่ต่อสู้",4),
 ("Five-card PLO preview", "คำเกริ่นบท PLO ห้าใบที่ยังไม่มี",6),
],
"getting-the-answer-key": [( "The Answer Key", "ใบชี้ทางเฉลย",1)],
"getting-the-spreadsheets": [( "My Spreadsheets", "ใบชี้ทางสเปรดชีต",1)],
"negreanu-holdem-wisdom": [
 ("Top Ten Rookie Mistakes", "1 ความผิดพลาดมือใหม่สิบข้อ",14),
 ("Top 5 Reasons Why You're Losing at Poker", "2 เหตุผลห้าข้อที่ยังแพ้",18),
 ("Table Talk", "3 การพูดคุยที่โต๊ะ",21),
 ("Three Levels of Poker", "4 ความคิดสามระดับ",24),
 ("What Are You Looking At?", "5 สังเกตอะไร",27),
 ("Home Run Hitters vs. Small Ball Players", "6 สายพอตใหญ่กับสายเก็บพอตเล็ก",30),
 ("To Show or Not to Show?", "7 ควรเปิดไพ่หรือไม่",33),
 ("Beating Up on the Weak Player", "8 เล่นกับคนอ่อน",36),
 ("Bullying a Bully", "9 รับมือคนกดดัน",39),
 ("The Five Times Rule", "10 กฎห้าเท่า",42),
 ("Aggressive Play vs. Conservative Play", "11 เล่นบุกกับเล่นระวัง",45),
 ("The Deadly All-in Bet", "12 ออลอิน",48),
 ("Betting Basics: When Less is More", "13 ขนาดเบตเล็กที่ได้ผล",51),
 ("The Value of Suited Cards", "14 ค่าไพ่ดอกเดียวกัน",54),
 ("Stealing Blinds", "15 แย่งบลายด์",57),
 ("Be Careful What You Learn on TV", "16 ระวังบทเรียนจากโทรทัศน์",60),
 ("Pondering Pocket Jacks", "17 คิดกับคู่แจ็ก",63),
 ("What's the Big Deal About Big Slick?", "18 ค่า AK",66),
 ("Top Ten Trouble Hands", "19 ไพ่ปัญหาสิบแบบ",69),
 ("Isolating Your Opponent in Limit Hold'em", "20 ไอโซเลตในลิมิตโฮลเอ็ม",72),
 ("Playing Trash Hands", "21 เล่นไพ่ต่ำ",75),
 ("Calling with the Worse Hand", "22 คอลด้วยไพ่ด้อยกว่า",78),
 ("Dangerous Hands to Play, Dangerous Hands to Own", "23 ไพ่ที่เล่นยากและถือยาก",82),
 ("Playing on a Short Stack", "24 เล่นเงินกองสั้น",85),
 ("Controlling the Table with a Big Stack", "25 ใช้เงินกองใหญ่คุมโต๊ะ",88),
 ("Playing Fast, Playing Slow", "26 เล่นเร็วและดัก",91),
 ("Three Dangerous Flops", "27 ฟลอปอันตรายสามแบบ",94),
 ("Don't Get Married to Your Aces", "28 อย่ายึดติดกับ AA",97),
 ("Where To Sit at the Poker Table?", "29 เลือกที่นั่ง",100),
 ("The Check-Raise", "30 เช็กเรส",103),
 ("Table Position", "31 ตำแหน่งโต๊ะ",106),
 ("Limit Hold'em Tactics in No-Limit Hold'em Games", "32 เทคนิคจากลิมิตในเกมโนลิมิต",109),
 ("Setting Up a Bluff", "33 วางลำดับบลัฟ",112),
 ("The Top 10 Myths About Poker", "34 ความเชื่อผิดสิบข้อ",115),
 ("Playing the Player", "35 เล่นตามคู่ต่อสู้",118),
 ("Suited Connectors", "36 ไพ่เรียงดอกเดียวกัน",121),
 ("Heads-Up with Jerry Buss", "37 เฮดส์อัปกับเจอร์รี บัส",124),
 ("Why the House Always Wins", "38 เหตุที่เจ้ามือได้เปรียบ",127),
 ("Bankroll Management", "39 จัดการเงินทุน",130),
 ("Poker Math and Conditional Probability", "40 คณิตศาสตร์และความน่าจะเป็นมีเงื่อนไข",133),
 ("Pot Odds", "41 พอตออดส์",136),
 ("Soft Playing is Cheating: Play Hard or Don't Play", "42 การออมมือคือการโกง",139),
 ("Setting Up a Home Poker Tournament", "43 จัดแข่งที่บ้าน",142),
 ("Heads-Up Poker", "44 โป๊กเกอร์เฮดส์อัป",145),
 ("What to Look for in Heads-Up Poker", "45 สังเกตอะไรในเฮดส์อัป",148),
 ("Playing Short-Handed", "46 โต๊ะคนน้อย",151),
 ("World Series of Poker", "47 เวิลด์ซีรีส์ออฟโป๊กเกอร์",154),
 ("Exploiting Your Table Image", "48 ใช้ภาพลักษณ์โต๊ะ",157),
 ("Dealing with Bad Beats", "49 รับมือแบดบีต",160),
 ("Final Thoughts", "50 ส่งท้าย",164),
],
"the-theory-of-poker": [
 ("Chapter One: Beyond Beginning Poker", "บท 1 พ้นพื้นฐานโป๊กเกอร์"),
 ("Chapter Two: Expectation and Hourly Rate", "บท 2 ค่าคาดหวังและผลตอบแทนต่อชั่วโมง"),
 ("Chapter Three: The Fundamental Theorem of Poker", "บท 3 ทฤษฎีบทหลักของโป๊กเกอร์"),
 ("Chapter Four: The Ante Structure", "บท 4 โครงสร้างแอนตี"),
 ("Chapter Five: Pot Odds", "บท 5 พอตออดส์"),
 ("Chapter Six: Effective Odds", "บท 6 ออดส์ที่มีผลจริง"),
 ("Chapter Seven: Implied Odds and Reverse Implied Odds", "บท 7 อิมพลายด์ออดส์และด้านกลับ"),
 ("Chapter Eight: The Value of Deception", "บท 8 คุณค่าการพรางมือ"),
 ("Chapter Nine: Win the Big Pots Right Away", "บท 9 ชนะพอตใหญ่ทันที"),
 ("Chapter Ten: The Free Card", "บท 10 ไพ่ฟรี"),
 ("Chapter Eleven: The Semi-Bluff", "บท 11 เซมิบลัฟ"),
 ("Chapter Twelve: Defense Against the Semi-Bluff", "บท 12 ป้องกันเซมิบลัฟ"),
 ("Chapter Thirteen: Raising", "บท 13 การเรส"),
 ("Chapter Fourteen: Check-Raising", "บท 14 เช็กเรส"),
 ("Chapter Fifteen: Slowplaying", "บท 15 การดัก"),
 ("Chapter Sixteen: Loose and Tight Play", "บท 16 เล่นหลวมและแน่น"),
 ("Chapter Seventeen: Position", "บท 17 ตำแหน่ง"),
 ("Chapter Eighteen: Bluffing", "บท 18 การบลัฟ"),
 ("Chapter Nineteen: Game Theory and Bluffing", "บท 19 ทฤษฎีเกมกับบลัฟ"),
 ("Chapter Twenty: Inducing and Stopping Bluffs", "บท 20 ล่อและหยุดบลัฟ"),
 ("Chapter Twenty-one: Heads-Up On The End", "บท 21 เฮดส์อัปตอนท้ายมือ"),
 ("Chapter Twenty-two: Reading Hands", "บท 22 อ่านมือ"),
 ("Chapter Twenty-three: The Psychology of Poker", "บท 23 จิตวิทยาโป๊กเกอร์"),
 ("Chapter Twenty-four: Analysis at the Table", "บท 24 วิเคราะห์ที่โต๊ะ"),
 ("Chapter Twenty-five: Evaluating the Game", "บท 25 ประเมินเกม"),
],
"poker-face-of-wall-street": [
 ("CHAPTER 1 The Art of Uncalculated Risk", "บท 1 ศิลปะความเสี่ยงที่คำนวณไม่หมด"),
 ("CHAPTER 2 Poker Basics", "บท 2 พื้นฐานโป๊กเกอร์"),
 ("CHAPTER 3 Finance Basics", "บท 3 พื้นฐานการเงิน"),
 ("CHAPTER 4 A Brief History of Risk Denial", "บท 4 ประวัติการปฏิเสธความเสี่ยง"),
 ("CHAPTER 5 Pokernomics", "บท 5 เศรษฐศาสตร์โป๊กเกอร์"),
 ("CHAPTER 6 Son of a Soft Money Bank", "บท 6 เรื่องเล่าธนาคารเงินอ่อน"),
 ("CHAPTER 7 The Once-Bold Mates of Morgan", "บท 7 กลุ่มคนของมอร์แกน"),
 ("CHAPTER 8 The Games People Play", "บท 8 เกมที่ผู้คนเล่น"),
 ("CHAPTER 9 Who Got Game", "บท 9 ใครมีฝีมือ"),
 ("CHAPTER 10 Utility Belt", "บท 10 ชุดเครื่องมืออรรถประโยชน์"),
],
"mental-game-of-poker": [
 ("1 INTRODUCTION", "1 บทนำ"), ("2 FOUNDATION", "2 รากฐาน"),
 ("3 EMOTION", "3 อารมณ์"), ("4 STRATEGY", "4 กลยุทธ์แก้เกมจิตใจ"),
 ("5 TILT", "5 ทิลต์"), ("6 FEAR", "6 ความกลัว"),
 ("7 MOTIVATION", "7 แรงจูงใจ"), ("8 CONFIDENCE", "8 ความมั่นใจ"),
],
"peak-poker-performance": [
 ("1 What’s Your Why?", "บท 1 เหตุผลที่เล่น"),
 ("2 Create Winning Habits", "บท 2 สร้างนิสัยที่ช่วยชนะ"),
 ("3 Systematizing Success", "บท 3 ทำความสำเร็จให้เป็นระบบ"),
 ("4 Deconstructing the A Game", "บท 4 แยกองค์ประกอบเกมที่ดีที่สุด"),
 ("5 Common Psychological Hurdles", "บท 5 อุปสรรคจิตใจ"),
 ("6 Beating Procrastination", "บท 6 เอาชนะการผัดวัน"),
 ("7 Transform Your Mental Game", "บท 7 เปลี่ยนเกมจิตใจ"),
 ("8 Neuropsychology and Peak Poker Performance", "บท 8 สมองและผลงานสูงสุด"),
 ("9 Enhance Your Brain’s Performance: Brain Boosters", "บท 9 เพิ่มสมรรถนะสมอง"),
 ("10 Readers’ Questions", "บท 10 คำถามผู้อ่าน"),
],
"gto-crash-course": [
 ("Game Theory Basics", "พื้นฐานทฤษฎีเกม"),
 ("The AKQ Game", "เกม AKQ"),
 ("Exploitation (AKQ Game)", "ปรับหาจุดอ่อนในเกม AKQ"),
 ("The A-5 Game", "เกม A–5"),
 ("Exploitation (A-5 Game)", "ปรับหาจุดอ่อนในเกม A–5"),
 ("A-5 Game With Raising", "เกม A–5 ที่มีการเรส"),
 ("Using GTO+", "ใช้ GTO+"),
 ("GTO+ Strategy Building", "สร้างกลยุทธ์ใน GTO+"),
 ("Player Modeling", "สร้างแบบจำลองคู่ต่อสู้"),
],
"play-optimal-poker": [
 ("Introduction", "บทนำ"), ("Chapter 1: Understanding Equilibrium", "บท 1 เข้าใจดุลยภาพ"),
 ("Chapter 2: Polarized Versus Condensed Ranges", "บท 2 ช่วงไพ่แบบขั้วกับแบบรวมตัว"),
 ("Chapter 3: Reciprocal Ranges", "บท 3 ช่วงไพ่ตอบโต้"),
 ("Chapter 4: Get Real!", "บท 4 นำแบบจำลองสู่มือจริง"),
 ("Chapter 5: Crafting Exploitative Strategies", "บท 5 สร้างกลยุทธ์หาจุดอ่อน"),
 ("Chapter 6: Complex Ranges", "บท 6 ช่วงไพ่ซับซ้อน"),
 ("Chapter 7: Raising", "บท 7 การเรส"),
 ("Chapter 8: Putting It All Together", "บท 8 สังเคราะห์แนวคิด"),
],
"grinders-manual": [
 ("1 Introduction", "1 บทนำ"), ("2 Opening the Pot", "2 เปิดพอต"),
 ("3 When Someone Limps", "3 เมื่อมีคนลิมป์"), ("4 C-Betting", "4 ซีเบต"),
 ("5 Value Betting", "5 เบตเก็บมูลค่า"), ("6 Calling Opens", "6 คอลการเปิด"),
 ("7 Facing Bets - End of Action", "7 รับมือเบตเมื่อการกระทำจบ"),
 ("8 Facing Bets - Open Action Spots", "8 รับมือเบตเมื่อยังมีคนเล่นต่อ"),
 ("9 Combos and Blockers", "9 คอมโบและบล็อกเกอร์"), ("10 3-Betting", "10 สามเบต"),
 ("11 Facing 3-Bets", "11 รับมือสามเบต"),
 ("12 Bluffing the Turn and River", "12 บลัฟเทิร์นและริเวอร์"),
 ("13 3-Bet Pots And Balance", "13 พอตสามเบตและสมดุล"),
 ("14 Stack Depth", "14 ความลึกเงินกอง"), ("15 Appendices", "15 ภาคผนวก"),
],
"super-system-1": [
 ("Chapter One - General Poker Strategy", "บท 1 กลยุทธ์โป๊กเกอร์ทั่วไป"),
 ("Chapter Two", "บท 2 เปรียบเทียบลิมิตกับโนลิมิต"),
 ("Chapter Three - No Limit Hold'em", "บท 3 โนลิมิตโฮลเอ็ม"),
],
"super-system-2": [
 ("My Story", "เรื่องชีวิตของดอยล์"), ("The History of No Limit", "ประวัติโนลิมิต"),
 ("Online Poker", "โป๊กเกอร์ออนไลน์"), ("Exclusive Super/System 2", "เนื้อหาพิเศษ Super/System 2"),
 ("Specialize or learn", "เรียนหลายเกมหรือเชี่ยวชาญเกมเดียว"),
 ("Limit Hold'em Poker", "ลิมิตโฮลเอ็ม"), ("Omaha Eight or Better", "โอมาฮาไฮโล"),
 ("Seven Card Stud High Low Eight-or-Better", "เซเวนการ์ดสตัดไฮโล"),
 ("Pot Limit Omaha High", "พอตลิมิตโอมาฮาไฮ"), ("Triple Draw Poker", "ทริปเปิลดรอว์"),
 ("Tournament Overview", "ภาพรวมทัวร์นาเมนต์"), ("No Limit Hold'em", "โนลิมิตโฮลเอ็ม"),
 ("World Poker Tour", "เวิลด์โป๊กเกอร์ทัวร์"), ("Poker Glossary", "อภิธานศัพท์"),
],
"decide-to-play-great-poker": [
 ("Chapter 1 Decide to Decide", "บท 1 ตัดสินใจอย่างตั้งใจ"),
 ("Chapter 2 The Religion of Position", "บท 2 ความสำคัญของตำแหน่ง"),
 ("Chapter 3 To Raise or Not to Raise", "บท 3 การเรส"),
 ("Chapter 4 Cards? We Don’t Need No Stinking Cards", "บท 4 คิดเหนือไพ่ของตน"),
 ("Chapter 5 Everyone Bluffs", "บท 5 ทุกคนบลัฟ"),
 ("Chapter 6 The Art of Adjustment", "บท 6 ศิลปะการปรับตัว"),
 ("Chapter 7 Responding to Raises", "บท 7 รับมือเรส"),
 ("Chapter 8 A Short Chapter on Two Subjects", "บท 8 สองประเด็นสั้น"),
 ("Chapter 9 Flopping Huge", "บท 9 ฟลอปที่เข้าแรง"),
 ("Chapter 10 Big Flop, Bad Position", "บท 10 ฟลอปใหญ่ในตำแหน่งเสีย"),
 ("Chapter 11 Monsters of the Multi-Way", "บท 11 ไพ่ใหญ่ในพอตหลายคน"),
 ("Chapter 12 Flopping Big on a Textured Board", "บท 12 ฟลอปใหญ่บน wet board"),
 ("Chapter 13 Quick on the Draws", "บท 13 ไพ่รอ"),
 ("Chapter 14 Top Pair, Untextured Board", "บท 14 ท็อปแพร์บน dry board"),
 ("Chapter 15 Top Pair, Textured Board", "บท 15 ท็อปแพร์บน wet board"),
 ("Chapter 16 Bluffing", "บท 16 การบลัฟ"),
 ("Chapter 17 River Play In Position", "บท 17 ริเวอร์เมื่อมีตำแหน่ง"),
 ("Chapter 18 River Play Out of Position", "บท 18 ริเวอร์เมื่อเสียตำแหน่ง"),
 ("Chapter 19 Other Matters", "บท 19 ประเด็นอื่น"),
 ("Chapter 20 Management", "บท 20 การจัดการ"),
],
"winning-secrets-online-poker": [
 ("Chapter 1 So What Is This Online Poker Thing?", "บท 1 โป๊กเกอร์ออนไลน์คืออะไร"),
 ("Chapter 2 Getting Started", "บท 2 เริ่มต้น"),
 ("Chapter 3 The Mechanics of Online Poker", "บท 3 กลไกออนไลน์"),
 ("Chapter 4 Games You Can Play", "บท 4 ชนิดเกม"),
 ("Chapter 5 Cash Games versus Tournaments", "บท 5 เกมเงินสดกับทัวร์นาเมนต์"),
 ("Chapter 6 Playing the Game", "บท 6 วิธีเล่น"),
 ("Chapter 7 Cheating", "บท 7 การโกง"),
 ("Chapter 8 Starting Hands", "บท 8 ไพ่เริ่มต้น"),
 ("Chapter 9 The Flop and Fourth Street", "บท 9 ฟลอปและสตรีตสี่"),
 ("Chapter 10 The Turn and Fifth and Sixth Streets", "บท 10 เทิร์นและสตรีตห้าหก"),
 ("Chapter 11 Playing the River", "บท 11 ริเวอร์"),
 ("Chapter 12 Evaluating Your Play Using Spreadsheets", "บท 12 วิเคราะห์ด้วยสเปรดชีต"),
 ("Chapter 13 Analyzing Your Game Using Poker Software", "บท 13 วิเคราะห์ด้วยโปรแกรม"),
 ("Chapter 14 Turning Data into Discipline", "บท 14 เปลี่ยนข้อมูลเป็นวินัย"),
 ("Chapter 15 Maintaining a Stable Playing Environment", "บท 15 รักษาสภาพแวดล้อมเล่น"),
 ("Chapter 16 Conclusion", "บท 16 สรุป"),
],
"pot-limit-omaha-jeff-hwang": [
 ("1. The Big Play Objectives", "1 เป้าหมายพอตใหญ่"),
 ("2. Basic Play and Key Concepts", "2 หลักพื้นฐาน"),
 ("3. The Straight Draws", "3 ไพ่รอสเตรต"),
 ("4. Starting Hands and Pre-Flop Play", "4 ไพ่เริ่มต้นและก่อนฟลอป"),
 ("5. After the Flop", "5 หลังฟลอป"),
 ("6. Situations and Practice-Hand Quizzes", "6 สถานการณ์และแบบทดสอบ"),
 ("7. Miscellaneous Topics", "7 ประเด็นอื่น"),
 ("8. Limit Omaha Hi/Lo Split", "8 ลิมิตโอมาฮาไฮโล"),
 ("9. Pot-Limit Omaha Hi/Lo Split", "9 พอตลิมิตโอมาฮาไฮโล"),
],
"cash-game-killer": [
 ("1. Introduction", "1 บทนำ"), ("2. Rules of Texas Holdem", "2 กติกาโฮลเอ็ม"),
 ("3. Getting Started", "3 เริ่มต้น"), ("4. Preflop Strategy", "4 ก่อนฟลอป"),
 ("5. Postflop Strategy", "5 หลังฟลอป"), ("6. Draws", "6 ไพ่รอ"),
 ("7. Playing Made Hands", "7 ไพ่สำเร็จ"), ("8. Crushing Your Opponents", "8 หาจุดอ่อนคู่ต่อสู้"),
 ("9. Advanced Strategy", "9 กลยุทธ์ขั้นสูง"), ("10. Closing Thoughts", "10 ส่งท้าย"),
 ("11. Glossary", "11 อภิธานศัพท์"), ("12. Extras", "12 ภาคเสริม"),
],
"gripsed-mtt-strategy-guide": [
 ("Chapter 1: Pre-Game Strategy", "บท 1 เตรียมก่อนแข่ง"),
 ("Chapter 2: Early Stage Strategy", "บท 2 ช่วงต้น"),
 ("Chapter 3: Middle Stage Play", "บท 3 ช่วงกลาง"),
 ("Chapter 4: Late Stage Play", "บท 4 ช่วงท้าย"),
 ("Chapter 5: Defence, Offence", "บท 5 ตั้งรับและบุก"),
],
"poker-math-preflop-workbook": [
 ("Getting Started", "เริ่มต้น"), ("Equity Setups", "โจทย์อิควิตี"),
 ("Range Building", "สร้างช่วงไพ่"), ("Combos", "คอมโบ"),
 ("Blockers", "บล็อกเกอร์"), ("Pot Odds", "พอตออดส์"),
 ("Implied Odds", "อิมพลายด์ออดส์"), ("Breakeven Percentage", "เปอร์เซ็นต์คุ้มทุน"),
 ("Auto-Profit", "กำไรอัตโนมัติ"), ("Expected Value (EV)", "ค่าคาดหวัง EV"),
 ("Open-Raising", "เปิดเรส"), ("Isolating", "ไอโซเลต"),
 ("3betting", "สามเบต"), ("Squeezing", "สควีซ"),
 ("4betting", "สี่เบต"), ("Going All-In Preflop", "ออลอินก่อนฟลอป"),
 ("Answer Key", "เฉลย"), ("Major Takeaways", "สรุปหลัก"),
 ("Challenge Mode", "โหมดท้าทาย"),
],
"two-plus-two-nl-six-max": [
 ("Preface", "คำนำ"), ("Table Selection", "เลือกโต๊ะ"),
 ("Preflop", "ก่อนฟลอป"), ("Under The Gun (UTG)", "UTG"),
 ("Middle Position (MP)", "ตำแหน่งกลาง"), ("Cut Off", "คัตออฟ"),
 ("Button", "บัตตัน"), ("Blinds", "บลายด์"), ("Squeezing", "สควีซ"),
 ("Flop Play", "ฟลอป"), ("Turn Play", "เทิร์น"),
 ("River Play", "ริเวอร์"), ("Mentality", "จิตใจ"),
],
"hole-card-confessions": [
 ("About This Book", "เกี่ยวกับหนังสือ"), ("Introduction", "บทนำ"),
 ("Information", "ข้อมูล"), ("Player Types", "ชนิดผู้เล่น"),
 ("Range", "ช่วงไพ่"), ("Eagle Eyes", "สังเกตอย่างละเอียด"),
 ("Enter Steal Equity", "แย่งอิควิตี"), ("Exploiting a Range", "หาจุดอ่อนช่วงไพ่"),
 ("Advanced Concepts", "แนวคิดขั้นสูง"), ("A Field Trip", "ตัวอย่างภาคสนาม"),
 ("What Now?", "ขั้นต่อไป"), ("Quiz Answers", "เฉลยแบบทดสอบ"),
],
}

# Per-chapter reading purpose. These are concise interpretive notes, with
# detailed explanations and caveats retained in the thematic sections below.
CHAPTER_NOTES = {
"peak-poker-performance": [
 ("Turns values and goals into a daily plan.", "เปลี่ยนคุณค่ากับเป้าหมายเป็นแผนรายวัน"),
 ("Builds small repeatable habits and identifies personal weak points.", "สร้างนิสัยเล็กที่ทำซ้ำและหาจุดอ่อนเฉพาะตัว"),
 ("Measures systems and routines rather than outcome goals alone.", "วัดระบบกับกิจวัตร ไม่ดูผลลัพธ์อย่างเดียว"),
 ("Defines one's A-game, flow, focus, and pregame readiness.", "กำหนด A-game ภาวะลื่นไหล สมาธิ และความพร้อมก่อนเล่น"),
 ("Names tilt triggers, emotion patterns, and mental leaks.", "ระบุตัวกระตุ้นทิลต์ รูปแบบอารมณ์ และจุดรั่วทางจิต"),
 ("Explains procrastination and tests short work bursts, accountability, and environment design.", "อธิบายการผัดวันและลองทำงานช่วงสั้น มีคนช่วยรับผิดชอบ และจัดสภาพแวดล้อม"),
 ("Practices mindfulness, thought defusion, and acceptance.", "ฝึกสติ เว้นระยะจากความคิด และยอมรับสิ่งที่ควบคุมไม่ได้"),
 ("Connects brain systems and neuroplasticity to learning and tilt.", "เชื่อมระบบสมองกับการเปลี่ยนแปลงสมองต่อการเรียนและทิลต์"),
 ("Reviews exercise, food, sleep, mindfulness, and stress as performance inputs.", "ทบทวนการออกกำลัง อาหาร การนอน สติ และความเครียดที่ส่งผลต่อผลงาน"),
 ("Answers reader questions on memory, fear, moving up, focus, and tilt.", "ตอบคำถามเรื่องความจำ ความกลัว การขยับสเตก สมาธิ และทิลต์"),
],
"dn-workbook-9036": [
 ("Introduces the course and learning process.", "แนะนำคอร์สและวิธีเรียน"),
 ("Uses acting order to distinguish attack from defense.", "ใช้ลำดับการเล่นแยกฝ่ายบุกและรับ"),
 ("Compares range advantage across dry and connected boards.", "เทียบความได้เปรียบช่วงไพ่บน dry board และบอร์ดต่อเนื่อง"),
 ("Reads a hand by revising ranges after bet sizes.", "ปรับช่วงไพ่หลังเห็นขนาดเบตในมือจริง"),
 ("Practices GTO baselines, odds, and mathematical checks.", "ฝึกกลยุทธ์ฐานแบบ GTO ออดส์ และคณิตศาสตร์"),
 ("Plans continuation bets by board and opponent count.", "วางแผนซีเบตตามบอร์ดและจำนวนคู่ต่อสู้"),
 ("Tests check-raises as value and pressure lines.", "ทดสอบเช็กเรสเพื่อมูลค่าและกดดัน"),
 ("Accounts for stack depth and postflop coverage when three-betting.", "คิดความลึกเงินกองและการครอบคลุมบอร์ดเมื่อสามเบต"),
 ("Applies the three-bet plan to concrete hands.", "นำแผนสามเบตไปวิเคราะห์มือจริง"),
 ("Checks whether a bluff line tells a coherent story.", "ตรวจว่าลำดับบลัฟเล่าเรื่องไพ่ได้สมเหตุผล"),
 ("Reviews opponent tendencies and value-to-bluff ratios.", "ทบทวนนิสัยคู่ต่อสู้และสัดส่วนไพ่มูลค่าต่อบลัฟ"),
 ("Sizes bets to the intended calling or folding range.", "เลือกขนาดเบตตามช่วงไพ่ที่จะคอลหรือหมอบ"),
 ("Requires conditions for overbets and checks blockers.", "หาเงื่อนไขโอเวอร์เบตและตรวจบล็อกเกอร์"),
 ("Adjusts hand strength and bluffing to multiple opponents.", "ปรับความแข็งมือและบลัฟเมื่อมีหลายคู่ต่อสู้"),
 ("Mixes actions to avoid easy prediction while preserving fundamentals.", "ผสมการกระทำเพื่อลดการถูกอ่าน โดยรักษาหลักพื้นฐาน"),
 ("Tests mixed lines against a full hand sequence.", "ทดสอบแผนผสมกับลำดับมือจริง"),
 ("Finds costly leaks before and after the flop.", "หาจุดรั่วที่เสียมากก่อนและหลังฟลอป"),
 ("Changes opening and survival priorities in early/middle stages.", "ปรับการเปิดกับการรักษาชิปช่วงต้น/กลาง"),
 ("Treats bubble pressure according to stack size.", "ประเมินแรงกดดันบับเบิลตามขนาดเงินกอง"),
 ("Contrasts final-table pressure for big, middle, and short stacks.", "เทียบแรงกดดันโต๊ะสุดท้ายของเงินกองใหญ่ กลาง และสั้น"),
 ("Reassesses blinds, antes, and fold equity every stage.", "ประเมินบลายด์ แอนตี และโฟลด์อิควิตีใหม่ทุกช่วง"),
 ("Prioritizes value and effective stack in cash games.", "ให้ความสำคัญกับมูลค่าและเงินกองที่มีผลในเกมเงินสด"),
 ("Practices a consistent routine to hide one's own signals.", "ฝึกกิจวัตรสม่ำเสมอเพื่อซ่อนสัญญาณของตน"),
 ("Looks for deviations from a player's ordinary behavior.", "สังเกตความเบี่ยงจากพฤติกรรมปกติของคู่ต่อสู้"),
 ("Evaluates speech and physical tells with context.", "ประเมินคำพูดและท่าทางตามบริบท"),
 ("Checks tell hypotheses against reviewed hands.", "ตรวจสมมติฐานเทลด้วยมือที่ทบทวน"),
 ("Uses conversation to gather information without leaking it.", "ใช้การพูดเก็บข้อมูลโดยไม่เผยข้อมูลตนมากเกิน"),
 ("Keeps an ordered decision routine at the table.", "ใช้ลำดับคิดที่แน่นอนเมื่ออยู่ที่โต๊ะ"),
 ("Identifies one's tilt and recognizes opponents' tilt.", "รู้ทิลต์ตนและสังเกตทิลต์คู่ต่อสู้"),
],
"the-theory-of-poker": [
 ("Defines poker decisions by long-run money rather than pot count.", "วัดการตัดสินใจด้วยเงินระยะยาว ไม่ใช่จำนวนพอตที่ชนะ"),
 ("Connects single-decision expectation to hourly performance.", "เชื่อมค่าคาดหวังของการตัดสินใจกับผลตอบแทนต่อชั่วโมง"),
 ("Explains why opponents' mistakes against known cards transfer value; multiway cases qualify it.", "อธิบายมูลค่าที่ได้เมื่อคู่ต่อสู้เล่นผิดหากเห็นไพ่จริง พร้อมข้อจำกัดพอตหลายคน"),
 ("Shows how forced bets change opening requirements and urgency.", "แสดงว่าแอนตีเปลี่ยนเกณฑ์เข้าเล่นและความเร่งในการแย่งพอต"),
 ("Compares call price with the present pot and live outs.", "เทียบราคาคอลกับพอตปัจจุบันและเอาต์ที่ยังมีผล"),
 ("Adds future betting rounds to the cost of chasing a draw.", "รวมต้นทุนเดิมพันสตรีตหน้ากับการตามไพ่รอ"),
 ("Separates future winnings from future losses when a draw hits.", "แยกเงินที่จะได้กับเงินที่จะเสียเมื่อไพ่รอเข้า"),
 ("Values hiding hand strength only when opponents can react.", "ประเมินการพรางมือเมื่อคู่ต่อสู้สังเกตแล้วปรับได้"),
 ("Examines when protection in a large pot outweighs extra calls.", "ดูว่าเมื่อใดการปกป้องพอตใหญ่คุ้มกว่าการเรียกคอลเพิ่ม"),
 ("Distinguishes giving a free card from taking one via position or betting.", "แยกการให้ไพ่ฟรีจากการหาไพ่ฟรีด้วยตำแหน่งหรือการเบต"),
 ("Combines fold equity with the chance a weak hand improves.", "รวมโฟลด์อิควิตีกับโอกาสที่ไพ่อ่อนจะพัฒนา"),
 ("Explains responses when a bet may be a semi-bluff rather than a made hand.", "อธิบายการตอบโต้เมื่อเบตอาจเป็นเซมิบลัฟ ไม่ใช่ไพ่สำเร็จ"),
 ("Catalogues raises for value, protection, bluff, information, and free cards.", "แจกการเรสเพื่อมูลค่า ปกป้อง บลัฟ ข้อมูล และไพ่ฟรี"),
 ("Requires a bettor who will bet and conditions that justify the trap.", "ต้องมีคู่ต่อสู้ที่พร้อมเบตและเงื่อนไขที่ทำให้การดักคุ้ม"),
 ("Checks whether a strong hand can safely invite later action.", "ตรวจว่าไพ่แข็งปล่อยให้เล่นต่อได้ปลอดภัยหรือไม่"),
 ("Adjusts bluff and value frequency to how often the table calls.", "ปรับความถี่บลัฟและเก็บมูลค่าตามความชอบคอลของโต๊ะ"),
 ("Separates absolute seat order from relative position to a likely bettor.", "แยกตำแหน่งที่นั่งจากตำแหน่งเทียบกับคนที่น่าจะเบต"),
 ("Relates bluff price, pot size, future cards, and opponent count.", "โยงต้นทุนบลัฟ ขนาดพอต ไพ่สตรีตหน้า และจำนวนคู่ต่อสู้"),
 ("Uses game theory to limit how often a bluff can be exploited.", "ใช้ทฤษฎีเกมกำหนดความถี่บลัฟที่คู่ต่อสู้เอาเปรียบยาก"),
 ("Studies betting lines that invite or discourage an opponent's bluff.", "ศึกษาลำดับเบตที่ล่อหรือยับยั้งการบลัฟ"),
 ("Works through final-street heads-up checks, bets, calls, and raises.", "วิเคราะห์เช็ก เบต คอล และเรสเมื่อเหลือสองคนในสตรีตสุดท้าย"),
 ("Builds ranges from actions, exposed cards, and pot mathematics.", "สร้างช่วงไพ่จากการกระทำ ไพ่ที่เห็น และคณิตศาสตร์พอต"),
 ("Models what each player thinks the other player thinks.", "คิดว่าผู้เล่นแต่ละฝ่ายเชื่อว่าอีกฝ่ายคิดอย่างไร"),
 ("Compares the cost of possible mistakes at the table.", "เทียบต้นทุนของความผิดพลาดแต่ละทางที่โต๊ะ"),
 ("Combines structure, rules, and opponent skill when selecting a game.", "รวมโครงสร้าง กติกา และฝีมือคู่ต่อสู้เพื่อประเมินเกม"),
],
"poker-face-of-wall-street": [
 ("Frames uncertain choices through risk rules, incentives, and a trading-game example.", "วางกรอบการเลือกเมื่อไม่แน่นอนด้วยกฎความเสี่ยง แรงจูงใจ และเกมซื้อขายตัวอย่าง"),
 ("Explains poker hands, betting structures, hold'em, Omaha, stud, and draw for finance readers.", "อธิบายอันดับไพ่ โครงสร้างเบต โฮลเอ็ม โอมาฮา สตัด และดรอว์แก่ผู้อ่านการเงิน"),
 ("Introduces banks, exchanges, market theory, and a Wall Street poker-night vignette.", "แนะนำธนาคาร ตลาดซื้อขาย ทฤษฎีตลาด และเรื่องเล่าคืนโป๊กเกอร์วอลล์สตรีต"),
 ("Traces hedging, futures/options, crashes, and society's uneven acceptance of risk.", "ตามรอยการเฮดจ์ ฟิวเจอร์ส/ออปชัน วิกฤต และท่าทีสังคมต่อความเสี่ยง"),
 ("Uses poker's laws, networks, banking, and cheating to examine financial organization.", "ใช้กฎหมาย เครือข่าย ธนาคาร และการโกงในโป๊กเกอร์พิจารณาโครงสร้างการเงิน"),
 ("Mixes banking history with the author's poker-player education.", "ผสมประวัติธนาคารกับเส้นทางเรียนโป๊กเกอร์ของผู้เขียน"),
 ("Follows the 1979 crash, trading-pit culture, options, bonds, and a trader's apprenticeship.", "เล่าวิกฤตปี 1979 วัฒนธรรมเทรดดิ้งพิต ออปชัน พันธบัตร และการฝึกงานเทรด"),
 ("Compares luck, bluffing mathematics, liar's poker, and cooperative games.", "เทียบโชค คณิตศาสตร์บลัฟ เกม liar’s poker และเกมร่วมมือ"),
 ("Asks who has skill and how experiments, prediction, and learning reveal it.", "ถามว่าใครมีฝีมือ และการทดลอง การทำนาย กับการเรียนรู้เผยสิ่งนั้นอย่างไร"),
 ("Closes with utility, rationality, and making deals under uncertainty.", "ปิดด้วยอรรถประโยชน์ ความมีเหตุผล และการต่อรองเมื่อไม่แน่นอน"),
],
"mental-game-of-poker": [
 ("Introduces the mental-game problem and limits of generic psychology advice.", "เปิดปัญหาเกมจิตใจและข้อจำกัดของคำแนะนำจิตวิทยากว้าง ๆ"),
 ("Builds a learning framework for moving skills from conscious effort toward habit.", "สร้างกรอบเรียนรู้เพื่อย้ายทักษะจากการจงใจทำไปสู่นิสัย"),
 ("Distinguishes emotion itself from the beliefs and decisions that follow it.", "แยกอารมณ์ออกจากความเชื่อและการตัดสินใจที่ตามมา"),
 ("Uses recognition, breathing, logic injection, reminders, repetition, and quitting rules.", "ใช้การรู้ตัว หายใจ ใส่เหตุผล เตือนกลยุทธ์ ทำซ้ำ และกฎหยุดเล่น"),
 ("Maps tilt triggers including injustice, revenge, entitlement, and accumulated frustration.", "แยกตัวกระตุ้นทิลต์ เช่น ไม่ยุติธรรม เอาคืน คิดว่าตนควรได้ และหงุดหงิดสะสม"),
 ("Examines overthinking, second-guessing, performance anxiety, and fear of future losses.", "ตรวจการคิดมาก ลังเลซ้ำ ความกังวลผลงาน และกลัวการเสียในอนาคต"),
 ("Separates goal problems and boredom from simply lacking willpower.", "แยกปัญหาเป้าหมายกับความเบื่อจากการกล่าวว่าขาดวินัยอย่างเดียว"),
 ("Shows how results and variance distort estimates of one's actual skill.", "แสดงว่าผลลัพธ์กับความผันผวนบิดการประเมินฝีมือตนอย่างไร"),
],
"grinders-manual": [
 ("Defines EV and a bottom-up six-max cash learning sequence.", "นิยาม EV และลำดับเรียนเกมเงินสดหกคนจากพื้นฐาน"),
 ("Rates starting hands and opening choices by seat and table.", "ประเมินไพ่เริ่มต้นกับการเปิดตามตำแหน่งและโต๊ะ"),
 ("Uses the ISO triangle: frequent strength, fold equity, and position.", "ใช้สามเหลี่ยมไอโซ: โอกาสไพ่แข็ง โฟลด์อิควิตี และตำแหน่ง"),
 ("Selects flop continuation bets and sizes from range and board evidence.", "เลือกซีเบตฟลอปกับขนาดจากช่วงไพ่และบอร์ด"),
 ("Separates relative hand strength, thick/thin value, and slowplay tradeoffs.", "แยกความแข็งสัมพัทธ์ มูลค่าหนา/บาง และต้นทุนการดัก"),
 ("Compares cold calls in position, out of position, and blind battles.", "เทียบคอลเมื่อมีตำแหน่ง เสียตำแหน่ง และปะทะบลายด์"),
 ("Treats a call differently when it closes action and realizes equity.", "แยกการคอลเมื่อการกระทำจบและรับอิควิตีได้"),
 ("Defends made and unmade hands while later players may still act.", "ป้องกันทั้งไพ่สำเร็จและยังไม่สำเร็จเมื่อคนถัดไปยังเล่นได้"),
 ("Counts combinations and card removal to update ranges.", "นับคอมโบและไพ่ที่ตัดออกเพื่อปรับช่วงไพ่"),
 ("Contrasts polar and linear three-bets, squeezes, and bet sizing.", "เทียบสามเบตแบบขั้ว แบบเรียงแรง สควีซ และขนาดเบต"),
 ("Builds a full defense to three-bets and checks squeeze responses.", "สร้างแผนป้องกันสามเบตครบทางและรับมือสควีซ"),
 ("Tests double/triple barrels, delayed c-bets, probes, and bluff raises.", "ทดสอบยิงสอง/สามสตรีต ซีเบตช้า โพรบ และเรสบลัฟ"),
 ("Studies aggression and defense in three-bet pots with balance in view.", "ศึกษาฝ่ายบุกและรับในพอตสามเบตโดยคำนึงถึงสมดุล"),
 ("Adjusts preflop and postflop choices for deep or shallow effective stacks.", "ปรับก่อนและหลังฟลอปตามเงินกองที่มีผลลึกหรือตื้น"),
 ("Holds glossary, figures, and supporting reference matter.", "รวมอภิธานศัพท์ ภาพ และส่วนอ้างอิง"),
],
}

PAGE_OVERRIDES = {
    "peak-poker-performance": dict(enumerate([26, 46, 65, 87, 113, 140, 162, 187, 216, 234], 1)),
    "cash-game-killer": {1: 3, 4: 11, 11: 53},
    # This PDF scans two printed pages onto most physical pages. Every entry
    # below was checked against the first spread carrying that chapter.
    "the-theory-of-poker": dict(enumerate([10, 14, 19, 26, 30, 39, 43, 47, 51, 55, 62, 70, 80, 88, 91, 95, 98, 102, 110, 116, 120, 132, 139, 144, 150], 1)),
    "super-system-2": {8: 223, 10: 296, 11: 331, 12: 336, 14: 430},
    "super-system-1": {1: 2, 3: 42},
    "pot-limit-omaha-jeff-hwang": dict(enumerate([24, 39, 59, 77, 106, 125, 182, 201, 300], 1)),
    "crushing-the-microstakes": {3: 19, 10: 61, 12: 130},
    "hole-card-confessions": {5: 46, 9: 116},
    "gripsed-mtt-strategy-guide": dict(enumerate([4, 10, 17, 25, 31], 1)),
    "two-plus-two-nl-six-max": {1: 4, 5: 6, 8: 14},
    "strategies-beating-small-stakes-tournaments": {6: 46},
    "decide-to-play-great-poker": {17: 104, 18: 110, 19: 114, 20: 117},
    "winning-secrets-online-poker": dict(enumerate([17, 25, 31, 37, 57, 69, 78, 89, 114, 140, 159, 179, 211, 241, 249, 253], 1)),
    "poker-math-preflop-workbook": {10: 140, 11: 156, 17: 246},
}
ROW_PAGE_OVERRIDES = {
    "pokercoaching-cash-game-cheat-sheet": {1: 1, 2: 2, 3: 4, 4: 3},
    "pokercoaching-tournament-cheat-sheet": {1: 1, 2: 2, 3: 3, 4: 4, 5: 5},
    "mental-game-of-poker": {2: 66, 3: 169},
    "thai-document-915850": {3: 4},
    "pot-limit-omaha-jeff-hwang": {2: 59, 3: 106, 4: 201},
    "poker-math-preflop-workbook": {2: 140, 3: 156, 4: 246},
    "poker-face-of-wall-street": {1: 23, 3: 23},
    "super-system-1": {1: 2, 3: 42},
    "gripsed-mtt-strategy-guide": {1: 4, 2: 10, 3: 31},
    "dn-workbook-9036": {1: 4},
    "winning-secrets-online-poker": {3: 179},
    "play-optimal-poker": dict(enumerate([18, 46, 90, 126, 156], 1)),
    "super-system-2": {2: 105, 3: 165, 4: 224, 5: 265, 6: 296, 7: 331, 8: 415},
}
MULTI_PAGE_EVIDENCE = {
    "pokercoaching-cash-game-cheat-sheet": {4: (3, 5)},
    "thai-document-915850": {4: (1, 2, 5)},
    "pot-limit-omaha-jeff-hwang": {2: (59, 77), 3: (106, 125), 4: (201, 300)},
    "gripsed-mtt-strategy-guide": {2: (10, 17, 25)},
    "winning-secrets-online-poker": {3: (179, 211, 241)},
}

def normalize(s: str) -> str:
    return re.sub(r"[^a-z0-9ก-๙]+", " ", s.casefold()).strip()

BODY_START = {
    "poker-face-of-wall-street": 20,
    "mental-game-of-poker": 15,
    "grinders-manual": 9,
    "the-theory-of-poker": 10,
    "negreanu-holdem-wisdom": 12,
    "peak-poker-performance": 13,
    "play-optimal-poker": 7,
    "pot-limit-omaha-jeff-hwang": 14,
    "hole-card-confessions": 10,
    "super-system-2": 12,
    "super-system-1": 4,
    "gto-crash-course": 4,
    "two-plus-two-nl-six-max": 4,
    "winning-secrets-online-poker": 12,
    "decide-to-play-great-poker": 10,
    "micro-stakes-playbook-9049": 10,
    "crushing-the-microstakes": 11,
    "poker-math-preflop-workbook": 6,
    "dn-workbook-9036": 3,
    "cash-game-killer": 4,
    "gripsed-mtt-strategy-guide": 3,
    "strategies-beating-small-stakes-tournaments": 4,
}

def parse_page_document(document: str) -> list[tuple[int, str]]:
    out = []
    for page, section in source_page_sections(document).items():
        raw_lines = section.splitlines()
        for index, line in enumerate(prose_only(section).splitlines()):
            if line == "### OCR supplement (unverified)":
                raw_lines = raw_lines[:index]
                break
        page_text = "\n".join(raw_lines)
        fenced = re.search(r"(?m)^(`{3,})text\n(.*?)\n\1$", page_text, re.S)
        # Only the archived extraction can identify a heading. Metadata
        # and PDF-link labels are editorial text, not book evidence.
        out.append((page, fenced.group(2) if fenced else ""))
    return out

def read_pages(source_id: str):
    out = []
    for f in sorted((ROOT / "harnesses/EN/sources" / source_id).glob("pages-*.md")):
        s = f.read_text(errors="replace")
        out.extend(parse_page_document(s))
    return out

def locate(pages, phrase: str, source_id: str) -> tuple[int | None, bool]:
    target = normalize(phrase)
    first_body = BODY_START.get(source_id, 1)
    hits = []
    for page, body in pages:
        if page < first_body: continue
        lines = body.splitlines()
        for line in lines[:40]:
            n = normalize(line)
            if n == target:
                hits.append(page)
                break
    if hits:
        return hits[0], True
    # A prose mention near the top of a page is not a chapter opening.
    # If the title appears only in front matter, link the actual TOC page
    # and mark it as such in the generated route.
    for page, body in pages:
        if page >= first_body: continue
        if any(normalize(line) == target for line in body.splitlines()):
            return page, False
    for page, body in pages:
        if page < first_body: continue
        if target and target in normalize(body):
            return page, False
    return None, False

def pdf_path(source_id: str) -> str:
    t = (ROOT / "harnesses/EN/sources" / source_id / "index.md").read_text()
    return re.search(r"\]\(([^)]*\.pdf)\)", t).group(1).split("sources/pdf/", 1)[1]

def write_guide(lang: str, brief: dict, rows: list, pages: list):
    sid = brief["id"]
    out = ROOT / "harnesses" / lang / "guides" / f"{sid}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    title = brief["title"]
    if sid == "thai-document-915850": title = "Short-stack NLHE cash-game notes (Thai)" if lang == "EN" else "บันทึกเกมเงินสด NLHE เงินกองสั้น"
    linkroot = f"../../EN/sources/{sid}/index.md"
    pdf = f"../../../sources/pdf/{pdf_path(sid)}"
    lines = [f"# {title}", "", (f"Source: [{brief['title']}]({linkroot}) · {brief['pages']} physical PDF pages · [original PDF]({pdf})" if lang == "EN" else f"ต้นฉบับ: [{brief['title']}]({linkroot}) · PDF {brief['pages']} หน้าจริง · [เปิด PDF]({pdf})"), ""]
    if lang == "EN":
        lines += ["## Reading route", "", "Use the topic map below for the major sections, then open the linked physical PDF page and its page-faithful Markdown. PDF page numbers include covers and front matter; printed page numbers in the book may differ. The extracted text can omit diagrams, suits, tables, and page layout. Check the [source-quality notes](../sources/source-quality.md) for extraction limits.", ""]
    else:
        lines += ["## เส้นทางอ่าน", "", "ใช้แผนที่หัวข้อด้านล่างเพื่อเลือกบท แล้วเปิดหน้า PDF จริงกับข้อความ Markdown ที่สกัดตามหน้า เลขหน้า PDF รวมปกและคำนำ จึงอาจต่างจากเลขหน้าที่พิมพ์ในเล่ม ข้อความสกัดอาจขาดภาพ สัญลักษณ์ดอก ตาราง หรือรูปแบบหน้า ตรวจ [บันทึกคุณภาพต้นฉบับ](../../EN/sources/source-quality.md) เพื่อดูข้อจำกัดการสกัด", ""]
    outline = OUTLINE.get(sid)
    if outline:
        external = sid.startswith("pokercoaching-")
        route_intro = (f"{len(outline)} physical page sections mapped; {len(rows)} study themes explained below. This short sheet has no table of contents."
                       if external and lang == "EN" else f"จับคู่เนื้อหาตามหน้าจริง {len(outline)} หน้า และอธิบายแก่นเรื่อง {len(rows)} กลุ่ม ชีตสั้นนี้ไม่มีสารบัญ"
                       if external else f"{len(outline)} major contents entries mapped; {len(rows)} study themes explained below. **TOC** links point to a detected contents entry; **reference only** means the chapter start is unverified."
                       if lang == "EN" else f"จับคู่หัวข้อสารบัญหลัก {len(outline)} รายการ และอธิบายแก่นเรื่อง {len(rows)} กลุ่มด้านล่าง **สารบัญ** คือหน้ารายการสารบัญที่พบจริง ส่วน **หน้าอ้างถึง** หมายถึงยังยืนยันหน้าเปิดบทไม่ได้")
        lines += ["## Original chapter route" if lang == "EN" else "## เส้นทางบทต้นฉบับ", "", route_intro, ""]
        chapter_notes = CHAPTER_NOTES.get(sid, [])
        assert not chapter_notes or len(chapter_notes) == len(outline), sid
        for i, entry in enumerate(outline):
            en, th = entry[:2]
            override = PAGE_OVERRIDES.get(sid, {}).get(i + 1)
            if override is not None:
                p, verified = override, True
            elif len(entry) > 2:
                p, verified = entry[2], True
            else:
                p, verified = locate(pages, en, sid)
            marker = "" if verified else ((" **TOC**" if lang == "EN" else " **สารบัญ**") if p is not None and p < BODY_START.get(sid, 1) else (" **reference only; chapter start unverified**" if lang == "EN" else " **หน้าอ้างถึง; ยังยืนยันหน้าเปิดบทไม่ได้**"))
            note = (" — " + chapter_notes[i][0 if lang == "EN" else 1]) if chapter_notes else ""
            target = f"{pdf}#page={p}" if p is not None else linkroot
            lines.append(f"- [{en if lang == 'EN' else th}]({target}){marker}{note}")
        lines.append("")
    lines += ["## Explained study themes" if lang == "EN" else "## คำอธิบายแก่นเรื่อง", ""]
    for row_idx, (en, th, en_note, th_note, phrase) in enumerate(rows, 1):
        override = ROW_PAGE_OVERRIDES.get(sid, {}).get(row_idx)
        p, verified = (override, True) if override is not None else locate(pages, phrase, sid)
        evidence_pages = MULTI_PAGE_EVIDENCE.get(sid, {}).get(row_idx, (p,) if p is not None else ())
        evidence = []
        for evidence_page in evidence_pages:
            chunk_start = ((evidence_page-1)//8)*8+1
            chunk_end = min(chunk_start+7, brief["pages"])
            chunk = f"../../EN/sources/{sid}/pages-{chunk_start:04d}-{chunk_end:04d}.md#pdf-page-{evidence_page}"
            evidence.append((f"[PDF p. {evidence_page}]({pdf}#page={evidence_page}) · [extracted page]({chunk})" if lang == "EN" else f"[PDF หน้า {evidence_page}]({pdf}#page={evidence_page}) · [ข้อความที่สกัด]({chunk})"))
        label = (" · section start unverified; inspect cited page" if lang == "EN" else " · ยังยืนยันหน้าเปิดหัวข้อไม่ได้ โปรดตรวจหน้า") if not verified and override is None and row_idx not in MULTI_PAGE_EVIDENCE.get(sid, {}) else ""
        citation = " · ".join(evidence) if evidence else (f"[source index]({linkroot})" if lang == "EN" else f"[ดัชนีต้นฉบับ]({linkroot})")
        lines += [f"### {en if lang == 'EN' else th}", "", en_note if lang == "EN" else th_note, "", (f"Evidence: {citation}{label}" if lang == "EN" else f"หลักฐาน: {citation}{label}"), ""]
    if lang == "EN":
        lines += ["## Scope and verification", "", "This is a source-specific study map and paraphrase, not a reproduction of the book or a solver-approved strategy. Work numerical examples, hand charts, quizzes, and figures against the linked original pages. Promotional/front-matter text and historical claims are not treated as current poker rules or proven results.", ""]
    else:
        lines += ["## ขอบเขตและการตรวจสอบ", "", "นี่เป็นแผนที่อ่านและคำอธิบายเฉพาะเล่ม ไม่ใช่การคัดลอกทั้งเล่มหรือกลยุทธ์ที่ผ่านการพิสูจน์ด้วยโซลเวอร์ ให้ตรวจตัวเลข ตารางไพ่ แบบทดสอบ และภาพกับหน้าต้นฉบับ ข้อความโฆษณา คำนำ และคำกล่าวอ้างตามยุคไม่ถือเป็นกติกาปัจจุบันหรือผลลัพธ์ที่รับประกัน", ""]
    if sid == "super-system-1":
        lines += ["The archived PDF is a 115-page **excerpt** containing only the three mapped sections; it is not the full multi-author *Super/System* volume." if lang == "EN" else "PDF ในคลังเป็น **ฉบับตัดตอน** 115 หน้า มีเพียงสามส่วนที่จับคู่ไว้ ไม่ใช่หนังสือ *Super/System* ฉบับเต็มที่มีผู้เขียนหลายคน", ""]
    if sid == "poker-math-preflop-workbook":
        lines += ["Extraction loses suit glyphs in many exercises and can turn Q into O. Read each hand and answer from the visual PDF before calculating." if lang == "EN" else "การสกัดข้อความทำสัญลักษณ์ดอกหายในโจทย์หลายข้อและอาจอ่าน Q เป็น O ต้องดูมือและคำตอบจาก PDF ที่เห็นภาพก่อนคำนวณ", ""]
    if sid == "getting-the-answer-key":
        lines += ["The PDF hyperlink annotations point to [online Google Sheet](https://splitsuit.pro/preflop-google-sheet) and [downloadable Excel version](https://splitsuit.pro/preflop-excel). These are external pointers; neither asset is included in the archive or verified here." if lang == "EN" else "ลิงก์ที่ฝังใน PDF ชี้ไปยัง [Google Sheet ออนไลน์](https://splitsuit.pro/preflop-google-sheet) และ [ไฟล์ Excel ดาวน์โหลด](https://splitsuit.pro/preflop-excel) ทั้งสองเป็นทรัพยากรภายนอก ไม่อยู่ใน ZIP และยังไม่ได้ตรวจเนื้อหา", ""]
    if sid == "pokercoaching-cash-game-cheat-sheet":
        lines += ["Assumed use: NLHE cash, with effective stack and rake supplied by the actual game. The source does not specify a rake schedule. All five pages are image-only; OCR text is unverified, so inspect the cited PDF for exact wording and card illustrations. Tournament payouts do not apply." if lang == "EN" else "การใช้: เกมเงินสด NLHE โดยต้องนำเงินกองที่มีผลและเรกจากเกมจริงมาใส่ ต้นฉบับไม่ระบุเรก ทั้งห้าหน้าเป็นภาพและ OCR ยังไม่ผ่านการตรวจทาน จึงควรดูคำและภาพไพ่จาก PDF ที่อ้างอิง โครงสร้างรางวัลทัวร์นาเมนต์ไม่เกี่ยวกับกรณีนี้", ""]
    if sid == "pokercoaching-tournament-cheat-sheet":
        lines += ["Assumed use: NLHE tournament, with effective stack in BB from the actual hand. Antes, payout structure and ICM model are not given, so the sheet's advice is not a calibrated push/fold or prize-EV chart. Page 4 is an illustrated hand-ranking chart; page 5 uses a Cash Game heading on a resource list." if lang == "EN" else "การใช้: ทัวร์นาเมนต์ NLHE โดยใช้เงินกองที่มีผลเป็น BB จากมือจริง ต้นฉบับไม่ระบุ ante โครงสร้างรางวัล หรือแบบจำลอง ICM จึงไม่ใช่ตาราง shove/fold หรือ prize EV ที่คำนวณตามเงื่อนไข หน้า 4 เป็นภาพลำดับไพ่ และหน้า 5 ใช้หัว Cash Game บนหน้ารวมทรัพยากร", ""]
    out.write_text("\n".join(lines))

def main():
    missing = {x["id"] for x in BRIEFS} - DATA.keys()
    assert not missing, missing
    for x in BRIEFS:
        pages = read_pages(x["id"])
        assert len(pages) == x["pages"], (x["id"], len(pages), x["pages"])
        for lang in ("EN", "TH"):
            write_guide(lang, x, DATA[x["id"]], pages)
    for lang in ("EN", "TH"):
        out = ROOT / "harnesses" / lang / "guides/index.md"
        mapped = sum(len(OUTLINE[x["id"]]) for x in BRIEFS)
        themes = sum(len(DATA[x["id"]]) for x in BRIEFS)
        lines = ["# Source-specific guides" if lang == "EN" else "# คู่มือแยกตามต้นฉบับ", "", (f"All {len(BRIEFS)} unique PDFs have a source-specific map: {mapped} main entries and {themes} explained study themes. The ZIP contains 26 entries (25 unique PDFs) because *Play Optimal Poker* occurs twice; two more PDFs come from PokerCoaching. Each guide links the original PDF and page-faithful corpus." if lang == "EN" else f"PDF ไม่ซ้ำทั้งหมด {len(BRIEFS)} เล่ม/เอกสาร จับคู่หัวข้อหลัก {mapped} รายการและอธิบายแก่นเรื่อง {themes} กลุ่ม ZIP มี 26 รายการ (ไม่ซ้ำ 25 ไฟล์) เพราะ *Play Optimal Poker* ซ้ำกัน อีก 2 ไฟล์มาจาก PokerCoaching ทุกคู่มือเชื่อม PDF ต้นฉบับและข้อความสกัดตามหน้า"), "", "| Source | PDF pages | TOC entries | Study themes | Guide |" if lang == "EN" else "| ต้นฉบับ | หน้า PDF | หัวข้อสารบัญ | กลุ่มคำอธิบาย | คู่มือ |", "|---|---:|---:|---:|---|"]
        for x in BRIEFS:
            sid = x["id"]
            title = "Short-stack NLHE cash-game notes (Thai)" if sid == "thai-document-915850" and lang == "EN" else ("บันทึกเกมเงินสด NLHE เงินกองสั้น" if sid == "thai-document-915850" else x["title"])
            lines.append(f"| {title} | {x['pages']} | {len(OUTLINE[sid])} | {len(DATA[sid])} | [guide]({sid}.md) |" if lang == "EN" else f"| {title} | {x['pages']} | {len(OUTLINE[sid])} | {len(DATA[sid])} | [อ่านคู่มือ]({sid}.md) |")
        lines += ["", ("Read the [English source corpus](../sources/index.md) for all page-level text and PDF links." if lang == "EN" else "ดู [คลังต้นฉบับภาษาอังกฤษ](../../EN/sources/index.md) เพื่อค้นข้อความตามหน้าและลิงก์ PDF"), ""]
        out.write_text("\n".join(lines))

if __name__ == "__main__": main()
