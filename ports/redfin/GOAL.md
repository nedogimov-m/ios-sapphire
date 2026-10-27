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

The complete buttons/native panel-controls block is committed8740ac2/cc100af
with typed standalone shim28dedaa. CI26 Actions40429125860/kernel22c5f154..
passes complete source/native ABI validation. V100 is terminal: no panic,
one server, clean1730084/Fastboot; full GPU/native Metal and all4panel checks
pass. PON/GPIO5 actual types/status and3key inputs are ready/armed,15000+reads
with zero errors, no physical presses. Initial DCS DBV409/off/on+restore
commands complete. Public UIKit brightness still fails, and ordinary output
regresses to0.199780FPS. Do not call controls or sustained GPU performance done.

Actual20H392 CoreBrightness requires IODisplayParameters/brightness/min/max/
value before creating its brightness module. The complete missing metadata/
raw+nits request/actual-value publication and separate native-backlight fix
now passes94combined tests plus all3exact native TUs. Exact883286e builds
in Actions40432973023/run27; watcher96353 prepares V101 after terminal
source/artifact/native ABI verification. ONE complete V101 integration is next. Reuse UI controls-v1/native035131 and all
existing Mesa/Metal/compiler artifacts; no repeated userland build is needed.
V103 is APPLIED/STALE/never reuse. Fresh V104 READ ONLY is complete at
actual1730084, empty journal/current preimages; no stage/apply/boot yet.
Phone/Photos auto opens remain OFF. Physical key actions, actual brightness,
lock/wake input, inset persistence, real-ALS auto brightness and full suspend
remain unverified/open. Exact builds/args/results are in NOTES.md. All wider
objective items above remain active.

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
