# GGPoker All-in or Fold (AoF)

- Stable ID: `29-gg-all-in-or-fold`
- Requires: aof, all-in or fold, all in or fold, allin or fold, ออลอินหรือโฟลด์, ออลอินออร์โฟลด์
- Scope: เกม cash All-in or Fold ของ GGPoker blind สแตก ค่าธรรมเนียมแบบตายตัวต่อมือ และการแก้เป็น push/fold
- English counterpart: [GGPoker All-in or Fold (AoF)](../../EN/topics/29-gg-all-in-or-fold.md)

## แนวคิดหลัก

All-in or Fold คือเกม cash ของ GGPoker ที่ทุกการตัดสินใจมีแค่ shove กับ fold สเตก Hold'em ต่ำสุดคือ $0.05/$0.10 โต๊ะ 4 คน ไม่มี ante ซื้อเข้า $1 ทุกคนจึงเริ่มที่ 10bb ที่นั่งว่างบ่อย จึงได้เล่น 3 คนหรือ heads-up ด้วย

rake ไม่ได้หักเป็นเปอร์เซ็นต์ของพอต แต่เป็นค่าธรรมเนียมตายตัวต่อมือ ที่ $0.05/$0.10 คือ rake 0.06bb, jackpot 0.07bb และ All-In Fortune $0.007 (0.07bb) รวมราว 0.2bb ต่อมือที่ถูกเก็บ สเตกสูงขึ้นเสียน้อยลงเมื่อคิดเป็น bb (ตั้งแต่ $0.50/$1 คือ rake 0.05bb กับ jackpot 0.05bb)

ค่าธรรมเนียมเก็บนอกพอต ประวัติมือจึงไม่มีบรรทัด rake และผู้ชนะได้ทั้งพอตเต็ม ๆ ดูผลได้เสียจริงจากยอดเงินหรือ PokerCraft ไม่ใช่จากพอต GGPoker ไม่ได้บอกว่าเก็บมือไหนบ้าง solver จึงสมมติว่าเก็บเฉพาะคนที่ถึง showdown ส่วน fold หรือ shove แล้วได้ blind ไม่เสีย ผลคือ call และ shove แคบลงเล็กน้อยเทียบกับ Nash ที่ไม่มี rake ค่าธรรมเนียมครึ่งหนึ่งกลับไปเป็นรางวัล jackpot ซึ่งออกนานครั้งและผันผวนสูง

## ตัวอย่างที่เรียบเรียงใหม่ (ไม่ได้คัดจากต้นฉบับ)

โต๊ะ 4 คน 10bb ทุกคน CO shove แล้ว fold มาถึง BB ในพอตมีอยู่แล้ว 11.5bb (CO 10, SB 0.5, BB 1) การ call ใส่เพิ่ม 9bb และเสียค่าธรรมเนียม 0.2bb ถ้าไม่มีค่าธรรมเนียม BB ต้องมี equity 9 / 20.5 = 43.9% แต่มีค่าธรรมเนียมต้องมี 9.2 / 20.5 = 44.9% ชาร์ตที่แก้แล้ว (`make chart` แล้วถาม `aof BB เจอ CO`) call ราว 15.5% ของมือ ส่วน CO shove เป็นคนแรกที่ 10bb ราว 24%

## วิธีใช้ solver

`make chart` หรือบอท Discord พูด `aof` หรือ `all-in or fold` พร้อมตำแหน่ง เช่น `aof BB เจอ CO`, `aof 3 handed BTN`, `aof SB 8bb` ค่าเริ่มคือ 4 คน 10bb ไม่มี ante ค่าธรรมเนียม 0.2bb ที่ showdown เปลี่ยนได้ทุกค่า แก้ชาร์ตทุกแบบล่วงหน้าแล้วส่งออก PDF ด้วย `.venv/bin/python scripts/export_aof_charts.py` ไฟล์อยู่ใน `tmp/aof/`

## หน้าต้นฉบับ

[GGPoker All-in or Fold table information](../../EN/sources/web/ggpoker-all-in-or-fold.md)

## หัวข้อที่เกี่ยวข้อง

[สแตกทัวร์นาเมนต์ ICM และ shove/fold](./13-tournaments-icm-pushfold.md) · [เกมเงินสด ไมโครสเตก และโต๊ะหกคน](./12-cash-microstakes-sixmax.md) · [อิควิตี พอตออดส์ และมูลค่าคาดหวัง](./04-equity-pot-odds-ev.md) · [สารบัญหัวข้อ](../INDEX.md)
