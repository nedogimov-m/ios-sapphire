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

Complete visible-content workload block passes56combined executable contracts
and actual20H392 UI3701524c../unchanged refresh6e9f8c83.. ABI/build. Existing
native internal windows/context identity, attached visible content and real
presentation-motion/model proof replace any-sublayer root-window admission.
New label system-content-subpixel is separate from the V99 workload. Raw output
counts remain even when workload proof refuses. No new graphics/kernel build.
Fresh V110 READ at1787750 is terminal, unmounted recovery idle, no apply/boot;
V107 image726d988f../nonce5e0963b86b5c97c8 passes full preflight. ONE combined
hardware run follows complete reversible stage/apply/readback/readonly fsck.
No new hardware/FPS result yet. All broader objectives below remain active.

V106 after4a34272 is TERMINAL exit0, authenticated231f94c6e5359d24,
one backboardd62/no panic or GPU fault, clean unmounted HFSX1787750 and
verified Fastboot. No live device operation. V109 APPLIED/STALE, never reuse;
next fresh V110 must bind1787750; next image/cycle V107. CI28 is rejected.
Accepted CI29 Actions40448042380/run29/source1e4b4dc/native8c422d8,
kernel11d60b4d.. retains all288canonical overlays and actual cold ABI.

Native248e974a../Metal5141bd25../cache496301fc.., UI5a501aac../refresh6e9f8c83..
are installed and source-exact. Both full independent GMEM/sysmem GLES modes,
whole app Metal and four physical references PASS. Actual original queued
wait2702438us/coldABI1/errno0 passes; ordinary native2s limits and real short/
nonblocking callers remain unchanged. The corrected full gate now admits real
BKS brightness/physical DBV514->157->768->514, off/output pause, wake/resume
and original level restoration, all PASS. Physical button presses, ALS, reboot
brightness persistence and full suspend are still unproved. Phone/Photos auto
opens and frame captures stay OFF; user confirms those apps work.

The subsequent finite window animation gives only2GPU frames/10.011176s=
0.199777FPS with90Hz callbacks and zero contacts. This is real output, not proof
of a continuously submitted visible workload or of a driver throughput limit.
Next complete block traces scene/layer/display-idle admission and makes actual
workload/output agree, preserving all native graphics/control checks and
failure/source ownership. Retain kernel/Metal/GLES/compiler/cache where
unchanged. V99/CI24/sourcee90b110 finite611frames/10.011138s=61.032FPS remains
preserved; universal smooth60/90FPS is unfinished.

Wi-Fi remains open:3known records,2visible names, no native association,
2NoAssociationWithNewMac flags and unsupported native property383. V99/V104/
V105 all observe unusable firmware MAC and the explicit per-boot random station
fallback. Stable station identity is missing; causal autojoin share and actual
Keychain password availability are unproved. Never change private wrapping
material or print credentials/addresses. ADSP sensor_process chre_utils fatal
persists. Every broader objective above remains active; exact build/args/results
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
