# Redfin remaining user goal — 2026-10-27

This replaces the stale V12 checkpoint and mirrors the revised active
`/goal`, registered on 2026-10-27 at the user's explicit request.
Completed bring-up is a preserved baseline; only remaining work is listed.

## Objective

Довести порт iOS 16.7.16 (20H392) на Pixel 5 (Redfin) по оставшемуся списку. Работать цельными блоками: сначала полностью реализовать связанный набор изменений, затем общий тест; без загрузок и тестов между минизадачами. Минимизировать подготовку и пересборки. Реализовывать и проверять всё доступное самостоятельно; телефон подключён. Откладывать только действия/проверки, требующие пользователя.

1) Довести работающий GPU-рендеринг (GLES GUI, Metal приложений) до устойчивых 60–90 FPS и быстрого отклика при панели 90 Гц. Устранить задержки подготовки/очередей/вывода, подтвердить корректность GMEM/sysmem и оптимизированного показа; исключить артефакты, чёрный экран, потерю тача/GPU, перезапуски SpringBoard и kernel panic.
2) Ускорить готовность Wi‑Fi, сохранять настоящий пароль штатно в Keychain, обеспечить автоподключение после перезагрузки с реальным интернетом.
3) Починить аппаратную яркость из интерфейса iOS, сохранение/восстановление уровня после блокировки и перезагрузки, автояркость от настоящего датчика.
4) Подключить кнопки питания и громкости: нажатия/удержания/отпускания, регулировка громкости, блокировка/пробуждение и штатные комбинации питания с громкостью. Сон/пробуждение должны сохранять рабочие экран, тач и GPU.
5) Починить сбрасывающийся отступ часов в статус-баре: стабильный обход реального выреза после блокировки, поворота, системных переходов и перезапуска SpringBoard, сохраняя полный экран.
6) Исправить модель на оригинальную для используемого iPhone X userland: согласованные название, аппаратный идентификатор, номер модели и артикул в формате Apple. Сохранить постоянные идентификаторы и реальный серийный номер. Довести настоящую авторизацию/активацию Apple ID и фактический вход пользователя в свой App Store; формат модели сам по себе не доказывает вход.
7) Реализовать мобильную связь через модем Redfin и телефонию iOS: SIM, регистрацию, оператора/сигнал, входящие/исходящие звонки с микрофоном/динамиком, SMS, мобильный интернет/APN и переподключение. LTE/5G/VoLTE — в пределах оборудования и оператора. Запуск Phone не считать доказательством связи.
8) По возможности реализовать eSIM через имеющуюся eUICC: обнаружение, добавление/активацию и выбор профилей с работающей связью. Недоступные компоненты и проверки с участием пользователя фиксировать отдельно.
9) Завершить питание/зарядку: достоверные аккумулятор/процент/статус/индикация, обнаружение кабеля/источника, настоящая зарядка и поддерживаемые проводные/беспроводные режимы с аппаратными пределами и защитами.
10) Довести thermald/thermalmonitord и все датчики до системной работы: реальные температуры, терморегулирование/защита, акселерометр, гироскоп, компас, приближение, освещённость, барометр и остальные из фактического инвентаря через интерфейсы iOS/CoreMotion. Имеющиеся показания/частотные переходы не означают полной интеграции.
11) Полностью реализовать камеры в штатном приложении и системных интерфейсах: основной/сверхширокоугольный задние и фронтальный модули, предпросмотр, фото, видео со звуком, поддерживаемые фокус/экспозицию, вспышку/фонарик, переключение, ориентацию и сохранение. Довести аппаратный тракт, прошивки, разрешения и жизненный цикл.

Готовые GUI, тач, Phone/Photos, Wi‑Fi/интернет, аппаратные GLES/Metal, полный экран, физические 90 Гц и серийный номер сохранять как базу; первичную реализацию заново не ставить. Phone/Photos автоматически в тестах не открывать. Неподтверждённое не считать готовым.

Приоритет oosexgang/hackios-xnu-kernel и hackios-xnu-userland; адаптировать Redfin/20H392 ABI, фиксировать reviewed commits в ports/redfin/UPSTREAM.md. После этапов обновлять NOTES.md, коммитить готовое, записывать сборки/boot args/результаты. Только временный fastboot boot; сохранять boot/recovery, модем/persist/EFS, userdata и бэкапы. Разрушительные действия согласовывать отдельно. Секреты, идентификаторы, дампы, логи и Apple-артефакты вне git. Завершение подтверждать фактами, отделять наблюдения от предположений.

## Current handoff

Complete persistent WLAN identity and native server/client admission block
passes94combined checks, actual complete WLAN/Topaz native TUs and signed
20H392 UIe82ff2b8../refresh2f570766.. build/import audit. Private station file
is persistent-local, never printed/regenerated; host/loader/kernel16byte ABI
selects it before vdev/ifnet/controller publication, preserving serial/wrapping/
RTC material and old diagnostic profiles. New production kernel ABI required.
Native23method server observer is one-boot/finite/read-only with original
callback arguments/results preserved; client context display/commit snapshots
are included. No forced rendering or changed model/state. No new graphics build.
Next exact-source CI30 must prove all CI29 overlays+the station identity overlay
(expected289), then ONE combined V108 after fresh V111/1797295 and complete
reversible preimages/readback/readonly fsck. No new device/CI operation or
Wi-Fi/autojoin/FPS proof yet. All11requirements remain active.

V107 afterbefea2e is TERMINAL exit0, authenticated5e0963b86b5c97c8,
one backboardd62/no panic or GPU fault, clean unmounted HFSX1797295 and
verified Fastboot. No live device/CI operation. V110 APPLIED/STALE, never reuse;
next fresh V111 must bind1797295; next image/cycle V108. CI28 is rejected.
Accepted CI29 Actions40448042380/run29/source1e4b4dc/native8c422d8,
kernel11d60b4d.. retains all288canonical overlays and actual cold ABI.

Native248e974a../Metal5141bd25../cache496301fc.., UI3701524c../refresh6e9f8c83..
are installed/source-exact. Both full independent GMEM/sysmem GLES modes,
whole app Metal and four private physical references PASS. Native manual BKS
brightness/DSI low/high, off/output pause, wake/output resume and original level
restoration PASS in V106 and V107. Physical key presses, ALS, reboot brightness
persistence and full suspend remain open. Phone/Photos auto opens/frame captures
stay OFF; user confirms those apps work. The Metal cold/default wait fix remains
proved; no retry or relaxed ordinary2s/real caller deadlines.

New native visible-content/context workload:11native windows; existing key
SBCoverSheetWindow content has a matching live context,40client presentation
samples/zero missing,1.777point motion, original model preserved. Yet physical
output only2GPU frames/10.011198s=0.199776FPS with90Hz callbacks. This does not
identify a GPU bottleneck or prove continuous render-server visibility. Complete
ordinary compositor/direct-output aggregate proof still refuses for sparse
frames. Next complete block traces native CA/render-server context/animation/
visibility/cadence admission and actual GUI submissions/retirement, including
idle/control transitions. Do not keep changing hosts without new evidence or
weaken full native gates. Reuse proved graphics/compiler/cache/kernel where
unchanged. New content workload differs from V99; its finite611frames/
10.011138s=61.032FPS baseline remains. Universal smooth60/90FPS unfinished.

Wi-Fi remains open:3known records,2visible names, no native association,
2NoAssociationWithNewMac flags and unsupported generic property383. Firmware
MAC unusable; per-boot random station fallback observed in V99/V104/V105.
Stable station identity and causal autojoin/real Keychain credentials remain
unproved. Readonly actual20H392 IO80211 SetProperty transport now audited:
UUIDf6acf84e../prefix5b95ad94.., fixed4104bytes/version1/length including NUL/
4096XML storage of one property entry, CFString key length<80. Resolved actual
CF serialization calls, no property values/identities/credentials read. Implement
full property semantics/stable identity/autojoin/startup together; no blind ACKs.
Never change private wrapping material. ADSP sensor_process chre_utils fatal
persists. Every wider objective above remains active; exact builds/args/results
and observations are in NOTES.md.

## Constraints and private state

Follow AGENTS.md, README.md and newest NOTES.md. Existing root updates must
be reversible, preimage-backed and fully readback-verified, with clean HFSX
and native readonly fsck. Never reuse an applied stage or an old root-generation
snapshot. Write every newly allocated block, including zero blocks.

Private identity is `backup/redfin/ios-device-identity.json`; persistent
wrapping material is `backup/redfin/ios-keychain-material.json` and must not
change. Native retained-RTC epoch mapping is
`backup/redfin/ios-rtc-anchor.json`. Do not print their secret values.
Implement features independently; defer only human-dependent actions and
verification, including real account login, not the implementation itself.
