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

Preserved performance baseline V99 / Actions40422287650/run24/sourcee90b110:
full native GPU/app Metal/private output/four physical references PASS,
611GPU frames/10.011138s =61.032FPS at90Hz callbacks, one stable backboardd.
This proves that finite workload, not universal smooth60/90FPS.

Native buttons/panel-controls are committed8740ac2/cc100af/28dedaa;
actual CoreBrightness metadata is883286e, built successfully in Actions
40432973023/run27 (kernel4f99141c..). V101 is TERMINAL exit0, no panic,
one server, clean1739626/Fastboot. Full native GPU/Metal/private pixels/four
panel references PASS; key readiness/15000+reads/errors0 and initial DCS
DBV/off/on+restore pass, with no physical presses. UIKit low/high still fail
(result6/restored1); finite output is2GPU frames/10.011262s=0.199775FPS.

The actual UIKit setter requires an application scene; an empty/software-dimming
host can also spoil the intended workload. Neither was logged in
V101, so the low counter rate is not conclusively attributed to GPU failure.
The complete observer correction now uses audited scene-independent native
BKS transactions and a visible nonempty content host.90combined executable
contracts and actual20H392 signed UI80745948../refresh4a02d6e1.. PASS.
No Mesa/Metal/compiler/kernel rebuild. V102 is TERMINAL exit0, one server/no
panic, clean1748928/Fastboot; native GPU/Metal/private pixels/four panel
references PASS. Native BKS low still never reaches hardware; result6/restored0,
low0/high0. The finite FPS workload correctly refuses after unproved restoration,
so no new FPS exists. Earlier low-rate causality remains open. Complete native standalone backlight selection and a finite owned SpringBoard
idle assertion are committed6a8399b;93combined contracts and actual14method/
four-image ABI/build PASS. V103 is TERMINAL exit0, no panic, one server,
clean1758944/Fastboot. Adapter installed/sync0/idle guard+release are observed,
but native CB module setup returns0; display-module start is never called.
BKS low/restore change logically; physical DBV409/200nits stays unchanged.
No new FPS exists: the observer incorrectly demands a new physical sequence
for an unchanged original state. Next complete block fixes restoration proof,
controls workload and original CB failure observation/integration together.
V106 APPLIED/STALE, never reuse; next fresh V107 must bind1758944. CI27 and
all Mesa/Metal/compiler artifacts stay retained unless actual evidence requires
kernel changes. Every wider objective remains open.
Phone/Photos auto opens remain OFF. Physical key actions, brightness from UI,
lock/wake input, inset persistence, real-ALS auto brightness and full suspend
remain unverified/open. Exact builds/args/results are in NOTES.md. Every wider
objective above remains active.

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
