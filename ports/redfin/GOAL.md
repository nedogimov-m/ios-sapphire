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

Preserved V99 / CI24 Actions40422287650/run24/sourcee90b110 baseline:
full native GMEM/sysmem/GLES/app Metal/private output/four panel references
PASS,611GPU frames/10.011138s=61.032FPS at90Hz callbacks, one server.
This proves that finite workload, not universal smooth60/90FPS.

Last actual V105/CI29 Actions40448042380/run29/source1e4b4dc/native8c422d8
is TERMINAL exit0, one backboardd/no panic, clean HFSX1778229/verified Fastboot.
Kernel11d60b4d.. has actual288entry old+new patch/cold ABI proof. V108 applied
ONCE with both preimage/readback ranges/readonly fsck; APPLIED/STALE, never
reuse. Next fresh V109 must bind1778229; next image/cycle V106. No live device
operation. CI28 remains REJECTED/forbidden, omitted native patch.

Both complete independent GMEM/sysmem GLES/direct/publication/budget contracts
PASS, as do four private output cases/four physical panel references. Actual
cold sequence355/shared10s deadline completes first output in4.951143s,
uncertainty0. Whole app Metal exits1: cache-surviving-pipeline completion fails,
context retires and later same-context cases refuse. Basic and fresh-context
Metal cases pass separately; this does not complete the full native contract.
The gate refuses controls/FPS before they start, no new performance result.
Initial real manual request/DBV409->514 succeeds; full physical UI brightness/
low/high/off/wake/persistence/ALS remain unproved. Key paths ready/armed7,
15000+samples/errors0, no physical presses. Phone/Photos auto opens remain OFF.

Next complete block coordinates AIR/Metal's own2s internal completion timeout
with CI29's bounded cold predecessor and ordinary2s native work, preserving
real short/nonblocking caller deadlines and failure/source ownership. V105's
generic completion error does not prove exact errno/timing. No new kernel
build indicated. Retain exact compiler/cache/GLES/UI where unchanged; verify
full native app Metal before controls/FPS, then ONE V106 hardware run after
fresh V109/preimages/readback/readonly fsck. V99 finite61.032FPS remains the
preserved performance baseline; no universal smoothness or wider completion.

Retained UI5a501aac../refresh6e9f8c83../native035131/Mesa1a4ad42c../
Metal17d0f01f../cache496301fc.. are current installed artifacts. Wi-Fi startup/
real credentials/autojoin still open:3known records,2visible names, no native
association request,2NoAssociationWithNewMac flags; generic property383 is
unsupported. Causality and actual password availability unproved. ADSP
sensor_process chre_utils fatal persists. Every broader objective above remains
active; exact builds/boot args/results and observations are in NOTES.md.

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
