# Changelog

## [0.41.0](https://github.com/DevSainir/Marketplace-Analytics/compare/v0.40.0...v0.41.0) (2026-10-26)


### Features

* **core:** print figures, money and dates in English, and stop requiring Russian ([5331224](https://github.com/DevSainir/Marketplace-Analytics/commit/533122499358cbc5bb06ddae6842768a6a25aca4))
* **finreports:** upload WB's weekly report by hand while the API holds it back ([c78a6d3](https://github.com/DevSainir/Marketplace-Analytics/commit/c78a6d30849d338aea68ed3c7f4efe12783929f2))
* run the whole app on fabricated data with `make demo` ([8bea3fa](https://github.com/DevSainir/Marketplace-Analytics/commit/8bea3faeb53e19db9b111cc6d874b2a5940d9974))


### Minor Features

* **ab-tests:** show the A/B tests in English ([ec00daf](https://github.com/DevSainir/Marketplace-Analytics/commit/ec00daf57595af7ede01af89bc68e48bebe3601b))
* **finreports:** «Логистика на 1 выкуп», and ROI red only below 30 % ([3e81cf2](https://github.com/DevSainir/Marketplace-Analytics/commit/3e81cf223968e7cb0154e91abb2f34d5435f8676))
* **finreports:** mark uncosted articles in the P&L and take their cost in place ([adddadd](https://github.com/DevSainir/Marketplace-Analytics/commit/adddadd5dc76cfc47a97fc94f1b13ca4b5978650))
* **finreports:** penalty reasons behind «N причин», so an article row stays one line high ([f666c4b](https://github.com/DevSainir/Marketplace-Analytics/commit/f666c4bb393b27200f04b1031f57183fdbfcc6ca))
* **finreports:** say «отчёт сформирован, ждём API» while WB holds it back ([f5aa5bf](https://github.com/DevSainir/Marketplace-Analytics/commit/f5aa5bfe9840249b62168cb550a0d5cf9f5e5dac))
* **finreports:** show the P&L in English ([d763880](https://github.com/DevSainir/Marketplace-Analytics/commit/d763880fa8338b5c0c6db8780878c17a92f6763a))
* **finreports:** the "Cost price" card says «Заполнить →» / «Изменить →» ([59e2e5f](https://github.com/DevSainir/Marketplace-Analytics/commit/59e2e5ff65858140b3a49f250a717a4e33531db2))
* **heatmap:** show the heatmap, advertising and summary pages in English ([a108019](https://github.com/DevSainir/Marketplace-Analytics/commit/a108019b1268848ef7e7e0af7760a951017a03c2))
* **labs:** run the monitoring sandbox on the workspace's own data ([cc7e310](https://github.com/DevSainir/Marketplace-Analytics/commit/cc7e310925e5dd4a1c8c8a63ea8e975a71932785))
* **monitoring:** show the SKU monitoring page in English ([4947492](https://github.com/DevSainir/Marketplace-Analytics/commit/494749286537386298cd59417cd0fe0f865d6026))
* **organizations:** grant every header page on its own, groups with any page that shows them ([7e774eb](https://github.com/DevSainir/Marketplace-Analytics/commit/7e774eb2502e7777c057c6184bae53373b8717d0))
* show the name Marketplace Analytics in the header, tab and mail ([c4d683a](https://github.com/DevSainir/Marketplace-Analytics/commit/c4d683ad05c5bc2716e11db9c76d5e346b8d960f))
* **users:** show sign-in, workspaces and the profile in English ([b644853](https://github.com/DevSainir/Marketplace-Analytics/commit/b64485352d549ddf49f64cf25b35cbb556d0dbbe))
* write alerts, the demo shop and the operator scripts in English ([19597c8](https://github.com/DevSainir/Marketplace-Analytics/commit/19597c8edd259d9198387f70449ad0cdc10878d1))


### Bug Fixes

* **ab_tests:** measure a test's duration once, not once per campaign ([a7ef9b8](https://github.com/DevSainir/Marketplace-Analytics/commit/a7ef9b881c2e1c6ce49c3fb6e2782cd4d9b88fd6))
* **ab-tests:** give the local photo store a directory the api user can write ([65d1176](https://github.com/DevSainir/Marketplace-Analytics/commit/65d1176ddcae3987c898dc20e07c345d68c696e0))
* **ab-tests:** keep the timeline's end stamp inside the card ([a7b96d0](https://github.com/DevSainir/Marketplace-Analytics/commit/a7b96d020d1a33077198acae36fdbae131308a2b))
* **ab-tests:** show the timeline's ticks on a phone ([e92a9e3](https://github.com/DevSainir/Marketplace-Analytics/commit/e92a9e3ca43655006aecff18f3e4149e93ce1439))
* **core:** let an outside monitor see when alerts stop reaching Telegram ([74e3b91](https://github.com/DevSainir/Marketplace-Analytics/commit/74e3b912d958a978b81fcc7caa6b10dac04cc8b2))
* **core:** make the env template run the local stack as it is ([a531584](https://github.com/DevSainir/Marketplace-Analytics/commit/a531584895c8612e2608bd2f27c874f96fd11396))
* **core:** no process may leak metric files, and a stuck worker restarts itself ([58049c1](https://github.com/DevSainir/Marketplace-Analytics/commit/58049c1f30cce6b9114d67b5dec378a289e840d8))
* **core:** replace nginx without taking the site down ([3a0ca02](https://github.com/DevSainir/Marketplace-Analytics/commit/3a0ca02f75dd92ddd802c9b6b06ea04569eb405c))
* **core:** send Telegram alerts through a dual-stack relay that retries ([95ee7d6](https://github.com/DevSainir/Marketplace-Analytics/commit/95ee7d6d9df1d096366f5b9b2f609311cdfe97f8))
* **core:** stop the healthcheck filling the worker's metrics tmpfs ([d0274f9](https://github.com/DevSainir/Marketplace-Analytics/commit/d0274f997f5237704e8c94dd3f971a2b5c247a16))
* **finreports:** do not promise a 15-minute check in the «ждём API» hint ([4bc4c3a](https://github.com/DevSainir/Marketplace-Analytics/commit/4bc4c3a9154571c7c1b1e722424b1ea64b0ad18a))
* **finreports:** keep the P&L cards and table still under "No cost price" ([7d59f53](https://github.com/DevSainir/Marketplace-Analytics/commit/7d59f530add36c5c133d0c025b697c1edad79f8b))
* **finreports:** let the P&L calendar reach the days the daily reports cover ([70097c2](https://github.com/DevSainir/Marketplace-Analytics/commit/70097c228d665f4ef00ed1c63414a4d65a9f1262))
* **finreports:** stop calling last Monday a lost day every Monday morning ([21caa90](https://github.com/DevSainir/Marketplace-Analytics/commit/21caa90d9c4cbb6a198e950296110b136ab84f73))
* **frontend:** show every time on the Moscow clock, labelled МСК ([3b74615](https://github.com/DevSainir/Marketplace-Analytics/commit/3b74615aaa1418e47556acca395b6daaa5a0649a))
* **monitoring:** campaign links follow the SKU on screen, not the first one opened ([4e148f0](https://github.com/DevSainir/Marketplace-Analytics/commit/4e148f0ffa555b30caa32221030c731cf58d2f76))
* **monitoring:** let "Overall" and "Organic" wrap instead of losing their last letters ([1c5cc83](https://github.com/DevSainir/Marketplace-Analytics/commit/1c5cc83e5beaecf8de6ab2843ecd19c2bd25998b))
* **monitoring:** the campaign id card keeps one line near the screen edge ([a868488](https://github.com/DevSainir/Marketplace-Analytics/commit/a868488753669cdd662dd9d3317ed3969fb9eb5e))
* stop citing one account's figures in the sources guide and alert texts ([f60b88b](https://github.com/DevSainir/Marketplace-Analytics/commit/f60b88bb19565a8104f3f810148eec36601f7379))
* **ui:** a sortable table head shows the pointer cursor ([5690515](https://github.com/DevSainir/Marketplace-Analytics/commit/5690515cefd66a07f04a5ef8093445761175cd3a))
* **ui:** nested size rows on a cool slate, not canvas grey ([0d1175e](https://github.com/DevSainir/Marketplace-Analytics/commit/0d1175ee8131f1b4504eb5cb5ae846612654e9d1))
* **workspaces:** let managers see the history backfill progress ([e8e8d2f](https://github.com/DevSainir/Marketplace-Analytics/commit/e8e8d2fa0c71dcc43c55ad27b696a510f7d768e3))


### Refactoring

* **finreports:** keep the module to the P&L, the balance and the harvest ([4c7795d](https://github.com/DevSainir/Marketplace-Analytics/commit/4c7795d185a6b734564bd05551a87d7bd906fa1c))
* **frontend:** drop the internal-features route guard and nav filter ([446c7d6](https://github.com/DevSainir/Marketplace-Analytics/commit/446c7d6fa8269d7dcf10cc12c38537a439ae8d6d))
* **organizations:** remove the internal-only access gate ([2c4734e](https://github.com/DevSainir/Marketplace-Analytics/commit/2c4734ee59cab35c28cecdbc28c20e3637abce01))
* **scripts:** split the demo settlement into its reports and their rows ([e2a3206](https://github.com/DevSainir/Marketplace-Analytics/commit/e2a32064c468e90157cc42483beaafb21c5b12c8))


### Documentation

* a finished task gets its journal row in the commit that closes it ([a9672d2](https://github.com/DevSainir/Marketplace-Analytics/commit/a9672d26e2501b800dc0e30e307ddf7543166cfd))
* add the README, with screenshots of the demo ([6effa63](https://github.com/DevSainir/Marketplace-Analytics/commit/6effa63e7498f6aef05ee1882d38d0f5df14c947))
* **backend:** translate comments in A/B tests, summary, users and the other modules ([5930817](https://github.com/DevSainir/Marketplace-Analytics/commit/59308173701e4c2fce9911c045afaa3f60891ef8))
* **backend:** translate comments in core, integrations, scripts and migrations ([e980c42](https://github.com/DevSainir/Marketplace-Analytics/commit/e980c4291de0fb5952d8458c2b34334eff4e9316))
* **claude:** rewrite CLAUDE.md and the skills for the public repository ([47825b8](https://github.com/DevSainir/Marketplace-Analytics/commit/47825b8ffc7d08ce0dcda28445dfa14a69772872))
* drop pointers into the removed security register ([159d627](https://github.com/DevSainir/Marketplace-Analytics/commit/159d627c0c02ed1e1624c64db85bebd41dae3a62))
* drop the journal rows whose work is not in the repository ([e9e1676](https://github.com/DevSainir/Marketplace-Analytics/commit/e9e1676251e29a2cab14c50e5d9800b084d1bf09))
* **finreports:** illustrate the forPaySum identity with round numbers ([1fe7ad4](https://github.com/DevSainir/Marketplace-Analytics/commit/1fe7ad4de6fcc351dcd3e37d2bdcb2a972d18c48))
* **finreports:** list the restored P&L tests in the verification table ([cf538fd](https://github.com/DevSainir/Marketplace-Analytics/commit/cf538fda31ff6c9afabe0564df3a4957126adfde))
* **finreports:** restore the P&L and migration notes in English ([7e3ffb9](https://github.com/DevSainir/Marketplace-Analytics/commit/7e3ffb9d4a47c4783857ed9bdf9c59e7676be913))
* **finreports:** state the filler-unit and rebill-VAT facts without figures ([d22e6d9](https://github.com/DevSainir/Marketplace-Analytics/commit/d22e6d9409ff6c0f2dbe05c690e9ad8f03c7d1b1))
* **finreports:** translate backend comments and docstrings to English ([91f7fda](https://github.com/DevSainir/Marketplace-Analytics/commit/91f7fda03e03ba80b3a2b85487f29a7aa9c8009c))
* **frontend:** say why the backfill strip stays silent on a refusal ([74e7f42](https://github.com/DevSainir/Marketplace-Analytics/commit/74e7f4203b15cd1cd2c69bbb2990472ca97641d8))
* **frontend:** translate comments in finreports, summary and heatmap to English ([ea73585](https://github.com/DevSainir/Marketplace-Analytics/commit/ea73585764908ce96f425a0979a0df95e9777633))
* **frontend:** translate comments in monitoring and advertising to English ([99ff8c1](https://github.com/DevSainir/Marketplace-Analytics/commit/99ff8c1ba355d804dfbf429c96f2cd823898814e))
* **frontend:** translate comments in profile, A/B tests and auth to English ([dcc672d](https://github.com/DevSainir/Marketplace-Analytics/commit/dcc672d1241db62962b048d6fac618cedb635605))
* keep explanations off the page and behind icons and tooltips ([d3e134f](https://github.com/DevSainir/Marketplace-Analytics/commit/d3e134f36cc1e3e5a9bacc3c87784686adbfc46d))
* **labs:** translate comments to English, call the sample cards samples ([3e6f5e4](https://github.com/DevSainir/Marketplace-Analytics/commit/3e6f5e432ea82daa45d375e4c4369a52691a6457))
* **monitoring:** translate backend comments and docstrings to English ([bd65b3e](https://github.com/DevSainir/Marketplace-Analytics/commit/bd65b3e689bb3957b038445a27bd685e7ad18bb2))
* point CLAUDE.md at the demo ([4a2d023](https://github.com/DevSainir/Marketplace-Analytics/commit/4a2d0239379d94a385c87760afb1d42b230d4d0f))
* **readme:** replace the hero poster with the demo video ([2188e86](https://github.com/DevSainir/Marketplace-Analytics/commit/2188e86ce8d2b8bcd06a098859f4c39b7ff52d30))
* record the A/B timeline end-stamp fix in the journal ([c0930b3](https://github.com/DevSainir/Marketplace-Analytics/commit/c0930b3c33f825c7d055f39e6ef2e74285566fc4))
* record the A/B timeline phone ticks fix in the journal ([bb72c92](https://github.com/DevSainir/Marketplace-Analytics/commit/bb72c923d1cd179db299f37e979c7187a6e0e204))
* record the blocking-client lint rule in the journal ([472dd95](https://github.com/DevSainir/Marketplace-Analytics/commit/472dd950dd317f155129e9f08f589a4e3109e35c))
* record the cancelled-request test fix in the journal ([3feeb4d](https://github.com/DevSainir/Marketplace-Analytics/commit/3feeb4d7dff7758351c45a58a5b676b2ba174f9f))
* record the demo in the journal ([76811f1](https://github.com/DevSainir/Marketplace-Analytics/commit/76811f10a9fc6842e4559613a996a05c3194d0fc))
* record the module-boundary test fix in the journal ([4db57c0](https://github.com/DevSainir/Marketplace-Analytics/commit/4db57c0a8da4e845f6b1a76160ca6c2aac9c7aa0))
* record the move of the whole product to English in the journal ([a1886eb](https://github.com/DevSainir/Marketplace-Analytics/commit/a1886eb41c2b5f115e24e0c83eb0ebafad247913))
* record the pre-publication check follow-ups in the journal ([bd843bf](https://github.com/DevSainir/Marketplace-Analytics/commit/bd843bfe40feb36e2bb266168ae527084d12d526))
* record the project name, the labs removal and the demo steps in the journal ([6deac20](https://github.com/DevSainir/Marketplace-Analytics/commit/6deac20294c31ee5b8206460ad8808a81fa8b01e))
* record the README rewrite in the journal ([ef1b009](https://github.com/DevSainir/Marketplace-Analytics/commit/ef1b009c6a96790e31d0b85c95e7990c0d16baf9))
* record the README, the CI move and the live sandbox in the journal ([fdb2541](https://github.com/DevSainir/Marketplace-Analytics/commit/fdb2541039058a2fd686829459f0dd6ace2941bf))
* record the relative-import lint rule in the journal ([c32f813](https://github.com/DevSainir/Marketplace-Analytics/commit/c32f813c1305194102b262712e40512115407d5a))
* record the removal of the internal-only gate in the journal ([81717a1](https://github.com/DevSainir/Marketplace-Analytics/commit/81717a18de70a13a39975a7e201f22a3c99575bc))
* record the Telegram relay, the pulled watchdog and the wider smoke probe ([5bbdf96](https://github.com/DevSainir/Marketplace-Analytics/commit/5bbdf960287e81b51a274e692d23899c316647d6))
* restore the journal of finished work and the live-position note in English ([a8b7a85](https://github.com/DevSainir/Marketplace-Analytics/commit/a8b7a8513fa04db73d3755bee841d8a02b9c17ea))
* retake the README screenshots on the English UI ([a859ee3](https://github.com/DevSainir/Marketplace-Analytics/commit/a859ee3988d40e61375fd35ce6f886146f39f9dc))
* rewrite the README around the live product, and add the AI policy ([f6b7e3d](https://github.com/DevSainir/Marketplace-Analytics/commit/f6b7e3dd8b55cdd9a32aa38467112a629598dfe2))
* **security:** record the edge cut-over as checked on the box ([b07bb53](https://github.com/DevSainir/Marketplace-Analytics/commit/b07bb535340266f3f8e220d8e98d407504bb641e))
* start the journal of finished work, backfilled since July ([680277e](https://github.com/DevSainir/Marketplace-Analytics/commit/680277eb7b285397cdb32ed45702742a1e5a82fa))
* tell measurements without naming the workspace they came from ([4b517a8](https://github.com/DevSainir/Marketplace-Analytics/commit/4b517a8dad2bbb46e249c6a5ac0883a6be5205d0))
* **tests:** translate component and integration test comments to English ([3ecc766](https://github.com/DevSainir/Marketplace-Analytics/commit/3ecc76615a38e391a1372342f95529e744f6ba5b))
* **tests:** translate unit-test comments and docstrings to English ([41b00ba](https://github.com/DevSainir/Marketplace-Analytics/commit/41b00ba25de289851fd38ce6d6be8430845f8a73))
* translate comments in the frontend core, infra and CI to English ([2de8e00](https://github.com/DevSainir/Marketplace-Analytics/commit/2de8e00374ab7a01105ccac287ad55b3642a4405))
* translate the docs to English and add SECURITY_DESIGN.md ([30589c3](https://github.com/DevSainir/Marketplace-Analytics/commit/30589c37894b332f9ac7f02a5c55ca61e7656053))
* write the P&L derivation, the README and the skills without Russian ([847c01d](https://github.com/DevSainir/Marketplace-Analytics/commit/847c01da6eb1cd38d64108dc31cf837dea29386d))


### Build System

* rename the compose project, images and package to marketplace-analytic ([d2c14e8](https://github.com/DevSainir/Marketplace-Analytics/commit/d2c14e8df2667fd9af9e6e7b883cb84cfd194dcd))


### CI/CD

* **core:** open P&L, the heatmap and A/B tests in the post-deploy smoke probe ([773bc56](https://github.com/DevSainir/Marketplace-Analytics/commit/773bc562b7507250c8f327f8877613df4ae9c0f2))
* drop steps and targets that pointed at removed infrastructure ([c719bee](https://github.com/DevSainir/Marketplace-Analytics/commit/c719beea218f5942ed938699fc147c2f4dff2c9c))
* run every workflow on GitHub-hosted runners ([5a6e871](https://github.com/DevSainir/Marketplace-Analytics/commit/5a6e871b74989ac60b43f76c8c2b320608bb511a))
* seed the browser and load tiers from the demo shop ([0701960](https://github.com/DevSainir/Marketplace-Analytics/commit/07019603257724a6d2e6f5e4b80a0fed58d67f5a))


### Chores

* **demo:** quote the workspace name the English way in the seed's summary ([0076b67](https://github.com/DevSainir/Marketplace-Analytics/commit/0076b672da467de0c4d8474175a98615a8ac9a93))
* **demo:** say what make demo is doing and how long it takes ([725d21a](https://github.com/DevSainir/Marketplace-Analytics/commit/725d21ae6e21738067571e5805bd901aad9011c6))
* **docker:** park the standby nginx and the edge in the local override example ([c1c37c0](https://github.com/DevSainir/Marketplace-Analytics/commit/c1c37c05acd88d6357549c6e31ecb4bba48f6747))
* **finreports:** log when WB's API first lists each report ([47becae](https://github.com/DevSainir/Marketplace-Analytics/commit/47becae77531c351becf4a601b5cd39fa64500f5))
* **frontend:** regenerate the API types from the current backend ([b5b6902](https://github.com/DevSainir/Marketplace-Analytics/commit/b5b6902e03f0e5f0c75b26eacebded30082536c3))
* **frontend:** regenerate the API types from the English OpenAPI ([ee5fb96](https://github.com/DevSainir/Marketplace-Analytics/commit/ee5fb96844634ddb35154bad29d7367f6712b41f))
* **frontend:** remove the labs sandboxes ([824a1f3](https://github.com/DevSainir/Marketplace-Analytics/commit/824a1f3559c8975adccd738dcffa9040d74a4663))
* **lint:** fail the backend lint on a blocking I/O client ([902c237](https://github.com/DevSainir/Marketplace-Analytics/commit/902c2378dccf87252ce08c5079601afd29f68f4f))
* **lint:** fail the backend lint on a relative import ([8a33ade](https://github.com/DevSainir/Marketplace-Analytics/commit/8a33aded5dbba8d3a9fa8d3c72bff0840bbd47be))
* name the project Marketplace Analytics ([b48bcee](https://github.com/DevSainir/Marketplace-Analytics/commit/b48bcee630277fe3938e0e35963287e6968bc7c4))
* record the gitleaks findings that are test values ([459d755](https://github.com/DevSainir/Marketplace-Analytics/commit/459d7558294a60c54f57ba4ccd01bdf4648a10a1))
* **release:** drop the Telegram release announcement ([69842c3](https://github.com/DevSainir/Marketplace-Analytics/commit/69842c352f0594ea5f830c53f4304d461cd71fc8))
