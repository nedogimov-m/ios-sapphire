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

Last actual V104/9cf6dca/CI27 Actions40432973023/run27/source883286e is
TERMINAL exit0, one backboardd/no panic, clean HFSX1768532/verified Fastboot.
Fresh V107 applied once with full preimages/readback/signatures/readonly fsck;
V107 is now APPLIED/STALE, never reuse. Next fresh root V108 must bind1768532;
next image/cycle V105. No live device operation.

Complete manual native brightness/workload/restoration block passes94combined
host contracts and signed actual20H392 UI5a501aac../refresh6e9f8c83.. ABI/build.
Actual native integrated context is observed and failed original setup admits
the manual driver; rawDBV514/native IOKit0/completed physical409->514 prove the
first real write. This does not complete physical UI low/high/persistence/ALS.
GMEM full native GLES/direct/budget, whole app Metal and four private physical
references PASS. Sysmem's simple shader/IOSurface/publication pass, but its
full direct first-reader exits27 (unchanged seed or failed lock not yet
separated). Approximately2s sampled surface wait is correlated only.
Correctness gate refuses controls/FPS before they run; no new performance
result. Key paths ready/armed7,15004samples/errors0, no physical presses.
Complete native first-reader/client-fence/output correction is implemented:
one actual FIFO cold sequence and immutable10s deadline, then ordinary2s work,
within original explicit caller bounds.124combined contracts and final11affected
checks/native GPU TU PASS. CI28 Actions40446572438 TERMINAL success but REJECTED: actual builder's duplicate
inventory omitted the new native overlay;287entries and no cold ABI markers.
It was never accepted/staged/booted. Duplicate inventory is now removed; the
actual CI staging loop consumes the canonical preparer list, with executable
order/missing-overlay checks PASS. Native8c422d8 block stays unchanged. Corrected
CI29 Actions40448042380/run29/source1e4b4dc is TERMINAL SUCCESS and accepted:
complete288entry map=CI27's unchanged287+new overlay, all cold/retained ABI,
actual kernel11d60b4d.. and fresh V105 image79fb2ec9../nonce2b3f4ef972a3cb39
full preflight PASS. Watcher57932 terminal exit0, never boots. Fresh V108 read
1768532 is preserved for stage/apply ONCE/ONE combined V105. Userspace GLES/
Metal/UI/compiler retained; CI28 forbidden. Corrected hardware result pending.
New hardware result remains pending. V99 is the preserved measured baseline.

Kernel4f99141c../Mesa1a4ad42c../Metal17d0f01f../native035131/cache496301fc.. stay
retained unless actual evidence requires changes. Wi-Fi readiness remains
36.665s from worker with no real autojoin/IP proof; actual ADSP sensor_process
chre_utils fatal persists. Phone/Photos automatic opens OFF. Physical UI
brightness/key actions, lock/wake input, clock inset persistence, real ALS/full
suspend and every wider objective remain open. Exact builds/args/results and
observations are in NOTES.md; keep the full goal active.

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
