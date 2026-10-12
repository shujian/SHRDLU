# SHRDLU 用法手册

> 项目首页（世界、分工、项目结构、设计决策）见 [`README.md`](README.md)；本文只讲**怎么用**：七个程序的参数、退出码、例子与速查。

## 一次测试的流程

1. **测试开始时**：测试者把初始场景交给被测者（一条 `observe`，带符号状态或一张图）。整次测试的世界信息就这一份。
2. **第一轮问句**：测试者逐条提问，被测者逐条作答，考的是它对初始状态的认识。
3. **指令**：测试者逐条下指令，被测者把操作调用回给测试者；测试者照那个调用执行，同时按指令执行出世界的当前状态，两边逐步对拍。
4. **第二轮问句**：测试者再问一组问句，考的是它对操作之后那些变化的认识。

每条消息一问一答：测试者发出、被测者回一条，测试者再发下一条。世界在指令之后变成什么样，由被测者从自己发出的那些调用推出来：它并不无知，而是**自信**，并且可能自信地错； **这份自信与世界的实际状态之差，就是"理解"的度量**。

一次测试依次走完这三段，**逐段给结论**：

```
env 交出初始场景（符号状态或一张图）
   ↓
第一轮问句：考对初始状态的认识
   ↓
逐条指令：testee 回操作调用，env 执行并与剧本对拍
   ↓
第二轮问句：考对变化后状态的认识
```

**一个操作做错不会让后面的问句失去意义**：第三步的基准是「被测者通过操作表现出的世界状态」，自洽即可答对。两份世界状态都由测试者维护，被测者那边只管发出调用和给出回答。

```
┌──────────────────────┐        一行一个 JSON         ┌──────────────────────┐
│      shrdlu-env       │  ←─────────────────────→   │    shrdlu-testee     │
│  当前状态 + testee 的    │  观察, 问句, 指令            │  私有世界模型          │
│  照调用执行 / 逐段判分  │  动作, 拒绝, 答句            │  解析英文 / 决策       │
└──────────────────────┘                             └──────────────────────┘
```

> **公开**：本文与 `README.md`（项目首页）、`docs/设计协议.md`、`docs/env功能介绍.md`、`docs/testee开发需求.md` 构成对外公开的正式材料（另有 `shrdlu.ini` 的参数说明）。过程与评审材料不在本仓库。项目介绍与设计推导见 `README.md`；本文只讲**如何使用**，分工与公开范围见 `README.md` §7。**参数不必背**：默认值都在 [`shrdlu.ini`](shrdlu.ini) 里，命令行只在这一次要改时用。

---

## 一分钟上手

**下文所有命令都假定当前目录是项目根目录（`SHRDLU/`）。**

```bash
export PYTHONPATH=.                      # 每个新终端一次

# 什么参数都不给：用 shrdlu.ini 里的默认值运行一次测试
python3 -m shrdlu.env.cli.env_main

# 造场景 → 出题 → 测试，一步到位
python3 -m shrdlu.env.cli.exam_main --seed 3 --play

# 或者：把整次测试做成一个可以拷给别人的 HTML 文件
python3 -m shrdlu.env.cli.report_main --seed 3 --out out/report.html
```

输出会是一份完整考卷：场景、指令序列、题库，最后运行一次测试以验证其可玩性。

---

## 环境

| 项 | 说明 |
| --- | --- |
| Python | **3.9+** |
| 依赖 | **无**（全部标准库） |
| 安装 | 不需要。`python3 -m shrdlu.env.cli.xxx` 直接可用 |
| 可选 | `pip install -e .` 之后可省掉 `python3 -m`，直接用 `shrdlu-env` 等命令 |
| 配置 | `shrdlu.ini`：参数只写一次，命令行按需覆盖（见下节） |

```bash
export PYTHONPATH=.        # 或者在每条命令前加 PYTHONPATH=.
```

---

## 配置：`shrdlu.ini`

参数大多不必每次写在命令行上。**每个键的默认值都写在 [`shrdlu.ini`](shrdlu.ini) 里并带注释**，那份文件就是参数的说明书；命令行参数只用来改这一次的行为。

```ini
[shrdlu]                                  # 公共段：所有程序都读
scenario           =                      # 默认场景（留空 = first-version）
questions          = 0                    # 0 = 用场景自带题库；大于 0 = 现场重出
testee             = example              # 已知实现名，或一条命令
observe            = state                # state 或 image
timeout            = 10.0

[shrdlu-exam]                             # 程序自己的段：覆盖公共段
questions          = 10
illegal            = 1
```

- **查找顺序**：`SHRDLU_CONFIG` 指的文件 → 当前目录及其各级父目录的 `shrdlu.ini` → 项目根目录的 `shrdlu.ini` → 内置默认值。找不到文件也能用（内置默认值即文件里的值）。
- **覆盖关系**（从强到弱）：**命令行 > 程序自己的段 > 公共段 > 内置默认值**。
- **归属**：某个程序自己声明的键（例如 `shrdlu-exam` 的 `questions = 10`）**只听自己的段**，公共段里的同名键不影响它；写错段（比如把 `level` 写进公共段）会当场报错。
- **分工**：命令行只说"这一次测试要什么"，常设参数留在文件里。留在命令行的是：考试从哪来（`--scenario` / `--scene` / `--questions` / `--seed`）、谁是被测者（`--testee` / `--impl`）、实验条件（`--observe` / `--no-labels`）、产物写到哪（`--out` / `--out-dir` / `--record`）、一次性动作（`--check` / `--play` / `--list`）与当场如何显示（`--pause` / `--quiet`）。搬进文件的都是环境形状的那几项：

  | 键 | 段 | 管什么 |
  | --- | --- | --- |
  | `shapes` | `[shrdlu]` | 现场出题允许的题型 |
  | `timeout` | `[shrdlu]` | 等被测者每条回复的秒数 |
  | `level` | `[shrdlu-scene]` | 场景等级 |
  | `reasoning_ratio` | `[shrdlu-exam]` | 「必须推演」的题所占比例下限 |
  | `scale` | `[shrdlu-render]` | PNG 的像素倍率 |
  | `model` / `ollama_url` | `[shrdlu-testee]` | 视觉模型与服务地址 |

- **想看当前生效的值**：

  ```bash
  python3 -m shrdlu.settings                  # 七个程序各读到了什么、来自哪个文件
  python3 -m shrdlu.settings --program env    # 只看 env
  python3 -m shrdlu.settings --write shrdlu.ini --force   # 重新生成一份带注释的默认文件
  ```

- **改坏了会说话**：值类型不对（`timeout = soon`）或缺文件（`SHRDLU_CONFIG` 指向不存在的路径）都会报出具体哪一行，程序以退出码 `2` 停下。

---

## 命令手册

每个程序都有 `--help`。下面的表列出全部参数，但**日常不用给参数**：默认值在 [`shrdlu.ini`](shrdlu.ini) 里，只有这一次要改的才写在命令行上。

### `shrdlu-env`：主持人（测试者）

加载场景、下发指令、出题、判分、记录。一次测试依次完成三段（问句 → 指令 → 再问一组问句）， **逐段给结论**，整次测试退出码取三段的合取。下表的"默认"列取自 [`shrdlu.ini`](shrdlu.ini)。

| 参数 | 默认 | 说明 |
| --- | --- | --- |
| `--scenario NAME_或_路径` | `first-version` | 场景名（从包内 `shrdlu/scenarios/` 找）或 `.json` 路径 |
| `--questions N` | `0` | 生成 N 道题**替代**场景自带题库；`0` = 用场景自带的 |
| `--seed S` | 无 | 给了 `--questions` 就是出题种子；**单独给**就现场造一整份考卷 |
| `--testee NAME_或_命令` | `example` | 已知实现名（`example`）、`模块:类`，或一条命令 |
| `--observe 形态` | `state` | 测试开始时给什么：`state`（符号）/ `image`（一张图） |
| `--record 路径` | 无 | 把测试记录写成 JSON |
| `--quiet` | 关 | 只打印一行结论 |

**退出码**：`0` = 判定理解 · `1` = 判定不理解 · `2` = 用法错误

常设参数不在这里，而在 [`shrdlu.ini`](shrdlu.ini)：题型过滤 `shapes`、等待上限 `timeout` 等（见「配置」一节的对照表）。

```bash
python3 -m shrdlu.env.cli.env_main                              # 运行默认场景
python3 -m shrdlu.env.cli.env_main --seed 3                     # 现场造一整份考卷
python3 -m shrdlu.env.cli.env_main --questions 15 --seed 13     # 默认场景 + 现场出 15 道题
python3 -m shrdlu.env.cli.env_main --testee frozen              # 用一个已知会错的实现
python3 -m shrdlu.env.cli.env_main --testee "python3 my.py"     # 换成自己的程序
python3 -m shrdlu.env.cli.env_main --record run.json            # 存下测试记录
```

`--quiet` 的那一行结论长这样，三段的数字各自列出：

```
first-version: 第一步（对初始状态的问句）: 10/10 -> 理解；第二步（操作）: 4/4 -> 理解；
第三步（对变化后状态的问句）: 5/10 -> 不理解, verdict=not_understood
```

`--record` 写的 JSON 里有每段的结论、每一步属于哪一段、以及两份世界状态与它们的差异；字段清单见 `docs/设计协议.md` §6.2。

### `shrdlu-testee`：被测方

从 stdin 读协议消息，从 stdout 回复。它只被展示一次世界。

| 参数 | 说明 |
| --- | --- |
| `--impl NAME` | `example`（默认），或自己的 `模块:类` |
| `--list` | 列出所有实现 |

```bash
python3 -m shrdlu.testee.cli.testee_main --list                  # 只有 example
python3 -m shrdlu.testee.cli.testee_main --impl example
python3 -m shrdlu.testee.cli.testee_main --impl my_testee:MyTestee
```

> 被测者可以被替换成**任何**会说这个行协议的程序。本仓库自带的只有一个最小示例（对问句答 `no`、对指令一律拒绝），用来打通链路；真正的实现由使用者自己写。

#### 看图观察

被测者也可以只看图：`observe` 的载荷给一张 PNG 而不是符号状态，**整次测试只有这一张**，读图一步交给视觉模型或自写的解码器。

```bash
# 开机给图而不是给状态
python3 -m shrdlu.env.cli.env_main --scenario first-version --observe image \
    --testee my_vision:MyTestee
```

图的边界写在 `render` 与测试里：**图的信息契约很小**，只需表达 **id / 形状 / 颜色 / 大小 / 直接放在谁上面**。唯一画不好的是**"在手中"** （那是左侧托盘，须依据虚线框识别），遇到这种场景 `render.require_covered` 会**明确报错**，而不是输出一张无法解读的图。

**Level 1 的世界是三种形状、三种位置**：`cube`／`pyramid`／`ball`，位置取「在桌面上 / 直接放在某物体上 / 在手中」三者之一，`ball` 也因此补上了形状题的第三个答案。容器（`box` 与"装进去"）是 SHRDLU 的招牌之一，属于更高场景等级（Level 2）的内容：画它要另加桌子下方那条内容条，是整张图里最弱的一处。

> 视觉模式需要 Pillow（先 `pip install pillow`）和一个能被调用的模型；核心库仍然零依赖，缺了它们只影响这一个实现。

### `shrdlu-scene`：造场景

生成初态（对象 + 位置关系）。**只造初态**；指令与题库是 `shrdlu-exam` 的事。

| 参数 | 说明 |
| --- | --- |
| `--seed S` | 一个种子（`3`）、一个区间（`1-5`）或一个列表（`1,4,9`） |

场景等级 `level` 是常设参数，在 [`shrdlu.ini`](shrdlu.ini) 的 `[shrdlu-scene]` 段。
| `--out 路径` | 单个场景写到这个文件 |
| `--out-dir 目录` | 批量时每个场景一个文件 |
| `--check 路径` | 不生成，改为检查一个已有场景是否合格 |
| `--quiet` | 只打印一行结论 |

```bash
python3 -m shrdlu.env.cli.scene_main --seed 3                       # 打印一个
python3 -m shrdlu.env.cli.scene_main --seed 1-5 --out-dir out/generated
python3 -m shrdlu.env.cli.scene_main --check shrdlu/scenarios/first-version.json
```

### `shrdlu-exam`：出题

给场景配上**指令序列**和**题库**，产出一份可测试的完整考卷。

| 参数 | 默认 | 说明 |
| --- | --- | --- |
| `--scene 路径` | 无 | 给这个场景出题；无则先按 `--seed` 造一个场景 |
| `--seed S` | `0` | 种子（也用于造场景） |
| `--steps N` | 3 或 4 | 指令条数（写死为 N） |
| `--illegal N` | `1` | 其中几条是**不可能执行的陷阱** |
| `--questions N` | `10` | 题目数量 |
| `--out 路径` | 无 | 写出完整考卷 |
| `--check 路径` | 无 | 不生成，改为校验一份已有考卷 |
| `--play` | 关 | 额外运行一次测试，验证其可玩性 |
| `--quiet` | 关 | 只打印摘要 |

「必须推演」的比例下限 `reasoning_ratio` 是常设参数，在 `[shrdlu-exam]` 段。

```bash
python3 -m shrdlu.env.cli.exam_main --seed 3 --play
python3 -m shrdlu.env.cli.exam_main --scene out/gen-l1-0003.json --out exam.json
python3 -m shrdlu.env.cli.exam_main --check exam.json
```

### `shrdlu-play`：逐步观看测试

每一步都停下来，显示**世界的当前状态**与 **被测者通过操作表现出的世界状态**，并允许使用者插话。

| 参数 | 默认 | 说明 |
| --- | --- | --- |
| `--scenario NAME_或_路径` | `first-version` | 场景名或 `.json` 路径 |
| `--questions N` | `0` | 生成 N 道题替代场景自带题库 |
| `--seed S` | 无 | 同 `shrdlu-env`：配 `--questions` 是出题种子，单独给就现场造一整份考卷 |
| `--observe 形态` | `state` | 测试开始时给 `state` 还是 `image` |
| `--testee NAME_或_命令` | `example` | 已知实现名、`模块:类`，或一条命令（命令走独立进程） |
| `--no-pause` | 关 | 不暂停，一次运行完毕 |

```bash
python3 -m shrdlu.env.cli.play_main --scenario first-version
python3 -m shrdlu.env.cli.play_main --seed 3                   # 现场造场景与题目，逐步观看
python3 -m shrdlu.env.cli.play_main --seed 3 --testee my_testee:MyTestee
python3 -m shrdlu.env.cli.play_main --testee "python3 my_testee.py"   # 独立进程的也能看
```

> 三个程序（`env` / `play` / `report`）都用同一条 `--testee`：值是已知实现名或 `模块:类` 就按名字启动，否则作为命令启动。

每次交换之后会打印（标题里带段名）：

```
═══ 第 12 步 · 第二步 · 指令
  env  →  Put the blue pyramid on the blue cube.
  ←  ok    action put_on('e', 'f')
  ── 世界的当前状态与 testee 通过操作表现出的世界状态（不一致处标 <<<）──
  id             what it is       world now         testee shows
  -----------------------------------------------------------------
  a              small red cube   on the table              on the table
  c              big red cube     on the table              on the table
  d              small blue ball  on the table              on the table
  e              big red pyramid  on f                      on the table  <<< 不一致
  f              big blue cube    on c                      on the table  <<< 不一致
  b              small yellow cube on a                      on a
```

**那行 `<<< 不一致` 就是全部意义所在**：第二步判分用的正是这份对照。

停机时可以做什么：

| 输入 | 作用 |
| --- | --- |
| 回车 / 空格 | 继续下一步 |
| `q <英文问句>` | 额外问一句（**不记入正式记录、不影响判定**） |
| `c <英文指令>` | 额外下一条（**会真的改变世界**，两份世界状态一起动，影响后续判定） |
| `s` | 重新显示状态 |
| `v` | 显示被测者至今的历史 |
| `h` | 帮助 |
| `x` | 结束测试 |

> 对照用的 **被测者通过操作表现出的世界状态** 由 **测试者** 维护，与被测者在哪一侧无关；被测者自己那份模型留在它那边。需要暂停与插话用这个程序；只看结果不看过程则用 `shrdlu-env`。

### `shrdlu-render`：把场景画成等轴测图

给视觉被测者看的图。**每个物体上画着它的 id，id 就是沟通用的唯一标识。**

```bash
python3 -m shrdlu.env.cli.render_main --scenario first-version --out scene.svg
python3 -m shrdlu.env.cli.render_main --seed 3 --out scene.png   # 扩展名决定格式
python3 -m shrdlu.env.cli.render_main --seed 3 --stage both --out-dir pictures
python3 -m shrdlu.env.cli.render_main --check --seed 3          # 完整性自检
```

| 参数 | 默认 | 说明 |
| --- | --- | --- |
| `--scenario NAME_或_路径` | 无 | 画这个场景；不给就按 `--seed` 现场生成 |
| `--seed S` | `0` | 生成场景用的种子 |
| `--stage 形态` | `initial` | `initial` / `final` / `both` |
| `--no-labels` | 关 | 不画 id 标签（更难的条件） |
| `--out 路径` | 无 | 单个输出；`.png` → 栅格图，其它 → SVG |
| `--out-dir 目录` | 无 | 每个状态一张，写 SVG |
| `--check` | 关 | 不写文件，反推几何与世界的当前状态比对 |
| `--quiet` | 关 | 只打印一行结果 |

**依赖**：SVG 零依赖；PNG 需要 Pillow（`pip install pillow`），视觉模型通常要 PNG。 PNG 的像素倍率 `scale` 是常设参数，在 `[shrdlu-render]` 段。

**如何查看**：

```bash
open scene.svg      # macOS，浏览器或预览
xdg-open scene.png  # Linux
# 或者直接拖进浏览器 / 预览窗口
```

画面结构：

- 桌子画成**菱形平面**（等轴测），`x` 向右下、`y` 向左下，场景本身是平面，就按平面绘制（若把 `y` 当作垂直位移，后排方块会**悬在桌面上方**）。
- 每个物体会画成有体积的立方体／金字塔／小球，id 用引线挂在一旁。
- 手爪里的物体画在左侧的虚线托盘上，标注 `in hand`。

> 这块区域**会写上名字**。不写的话它看起来就像一块来路不明的底色区。图要能自己解释自己。

绘制顺序按**深度**，同一堆叠按**从下到上**。顺序若有误，数据无从体现、图上却可直接看出：错误顺序会把下方的方块画到堆叠于其上的方块之上。

`--check` 会**从画出的几何反推状态**再与世界的当前状态比对：不是读回数据字段，而是按"谁的下沿贴着谁的上沿"推断堆叠关系。所以它检验的是**图本身是否信息无损**。

> 它证明的是一张图**足够**表达状态，**不证明**某个视觉模型**看得懂**（那只能靠实际运行一次）。另外 `--no-labels` 可以出一版没有标签的图，用来把 "指称错了"和"跟踪错了"分开诊断。

### `shrdlu-report`：把一整次测试做成一页网页

`shrdlu-play` 是**当场看**，`shrdlu-report` 是**事后看**：运行完一次测试后，把每一步的图、指令、回答、两份世界状态之差写入**一个 HTML 文件**。

```bash
python3 -m shrdlu.env.cli.report_main --scenario first-version --out out/report.html
python3 -m shrdlu.env.cli.report_main --seed 3 --out out/report-gen3.html
python3 -m shrdlu.env.cli.report_main --scenario first-version --testee frozen --out out/report-frozen.html
```

| 参数 | 默认 | 说明 |
| --- | --- | --- |
| `--scenario NAME_或_路径` | `first-version` | 用既有场景 |
| `--questions N` | `0` | 生成 N 道题替代场景自带题库 |
| `--seed S` | 无 | 配 `--questions` 是出题种子；单独给就现场造一整份考卷 |
| `--observe 形态` | `state` | 给 `state` 还是 `image` |
| `--testee NAME_或_命令` | `example` | 已知实现名、`模块:类`，或一条命令 |
| `--out PATH` | `report.html` | 输出 HTML 路径 |
| `--open` | 关 | 写好之后用浏览器打开 |
| `--quiet` | 关 | 只报结论 |

页面从上到下是：**头部**（场景名、被测者、种子、总判定、三段的分段结论）→ **初态图** → **按段分组的每一步**（该步的图、测试者说了什么、被测者回了什么、世界的当前状态与被测者表现出的世界状态 并排对照，不一致处高亮）→ **判定**（三段各自的结论 + 逐条错处）。

三个刻意的取舍：

- **自足单文件、零 JavaScript。** 图是内联 SVG，样式是内联 CSS，不引任何外部资源，也不放 `<script>`。断网、换机器、拷给别人都能开；也因为没有脚本，这页**只能看，不能改**：报告是只读视图，不许反过来影响判定。
- **图会去重。** 15 步的测试会产生 30 张图，其中大量重复（近的几步状态没变）。按内容去重后通常只剩 4–9 张。
- **不在报告里重写一遍渲染器。** 图由 `shrdlu-render` 同一套代码生成，不另写 JS 版。

> 这一页是**静态快照**：只能看一次测试。若需边运行边观察、或在页面里插话，那属于本地服务器版的功能，未实现。

---

## 一个完整的例子

从零到一次测试：

```bash
$ python3 -m shrdlu.env.cli.scene_main --seed 7 --quiet
gen-l1-0007: ok | 6 objects, 948 valid questions, shapes=all,attr,count,exists,rel, ...

$ python3 -m shrdlu.env.cli.exam_main --seed 7 --out exam.json --quiet
gen-l1-0007: 4 instructions (1 illegal), 10 questions, 5 reasoning (50%),
             pool 1761 of which 276 reasoning

$ python3 -m shrdlu.env.cli.env_main --scenario exam.json --quiet
gen-l1-0007: 第一步（对初始状态的问句）: 6/6 -> 理解；第二步（操作）: 4/4 -> 理解；
             第三步（对变化后状态的问句）: 10/10 -> 理解, verdict=understood
```

> 第一步只问到 6 道题：自动出的题是对着**指令之后**的状态出的，其余几道在初态下指不到对象（该堆叠在初态下不存在），测试者在第一步跳过它们、不计入分母。两轮的题目由测试者的题库决定（现行做法是同一份题库问两遍），题量因此不一定相同。

出题时**不加 `--quiet`** 能看到全部内容：

```
=== instructions ===
  1. ok      Put the blue cube on the big red cube.
  2. ok      Put the red pyramid on the blue cube.
  3. illegal Put the small red cube on the red pyramid.  (should be refused: cannot support)
  4. ok      Put the blue ball on the yellow cube.

=== questions ===
   1. [reason] Are all balls on the yellow cube on the red cube supported? -> yes
   2. [reason] Are all pyramids on the table?                   -> no
   3. [reason] How big is the pyramid on the blue cube?         -> big
   ...
   6. [recall] Are all balls clear?                             -> yes
   7. [recall] Are all cubes clear?                             -> no
```

注意第 3 条指令：**它是陷阱，而且是从前两条造成的状态里推出来的**，红金字塔的尖顶无法支撑其它物体，所以那条指令非法。只有一路跟踪了状态变化的被测者才会拒绝它。

`[reason]` = 答案因指令而改变（或初态下无法指称），**必须推演**才能答对。 `[recall]` = 答案没变，记住初始观察也能答对。

---

## 查看当前状态

```bash
git log --oneline            # 查看提交历史
git status                   # 应为空
git show --stat HEAD         # 最近一次改了什么

python3 -m unittest discover -s tests        # 全部测试（视觉模型测试默认跳过）
python3 -m unittest discover -s tests -v     # 逐条列出

cat README.md                # 项目首页：世界、分工、项目结构、设计决策（先读这份）
cat docs/设计协议.md          # 线上格式的规范文本
cat docs/env功能介绍.md      # 用 env / 接第三方 testee：env 提供什么、保证什么
cat docs/testee开发需求.md   # 要自己写 testee：必须实现什么、如何判定、如何自测
```

三个入口可快速判断整体状态：

```bash
python3 -m shrdlu.env.cli.scene_main --check shrdlu/scenarios/first-version.json   # 场景是否合格
python3 -m shrdlu.env.cli.exam_main  --check exam.json                      # 考卷还成立吗
python3 -m shrdlu.env.cli.env_main   --testee example --quiet              # 最小示例：链路是否通
```

---

## 目录结构

```
shrdlu/                 库
  world.py              世界状态与物理（位置、堆叠、手爪），两侧共享
  snapshot.py           状态 JSON（跨程序唯一的格式）
  protocol.py           消息格式（一行一个 JSON）
  ops.py                O0 操作集：合法性检查 + 执行
  questions.py          问句语义 + 英文生成器 + 按世界当前状态求值
  settings.py           读 shrdlu.ini：参数默认值与来源
  transport.py          独立进程与协议循环
  scenarios/            场景与考卷数据（**唯一一份**：手写场景在这里，测试、运行与 wheel 都用它）
  env/                  env 一侧（测试者）
    host.py             env 主循环、两份世界状态与逐段判分
    answers.py          答句归一与判分
    commands.py         指令的英文生成
    scenario.py         场景：初态 + 指令 + 题库（读 / 写 / 校验）
    generator.py        题库枚举与分层采样
    worldgen.py         场景生成与质量准则
    authoring.py        出题：指令序列 + 题库
    render.py           等轴测渲染（SVG / PNG）
    webreport.py        把一整次测试压成一个自足 HTML 文件
    impls.py            选 testee：进程内构建或起子进程
    cli/                六个命令行程序（env / scene / exam / play / render / report）
  testee/               testee 一侧（被测者）
    api.py              接口：Testee / Observation / Action / Refuse
    example.py          最小示例：只回拒绝，用来打通链路
    nlp.py              P0 英文解析器（只有这一侧需要）
    registry.py         按名字选实现（四个程序共用）
    cli/testee_main.py  testee 程序

README.md               项目首页：世界、分工、项目结构、设计决策（先读这份）
README-env.md           七个程序的用法手册（本文）
shrdlu.ini              参数默认值（带注释，命令行按需覆盖）
pyproject.toml          打包与入口点（七个命令）
agent.md                文档撰写要求（维护者）
tests/                  验收套件（每个阶段一个）
tools/check.sh          提交前的完整检查
docs/                   设计文档（公开部分）
                        设计协议.md        线上格式的规范文本
                        env功能介绍.md     env 提供什么、保证什么、稳定性承诺
                        testee开发需求.md  面向 testee 开发者：契约与验收清单
```

---

## 协议速查

测试者与被测者之间**一行一个 JSON 对象**。

**测试者 → 被测者**

```json
{"type": "observe",  "state": {"objects": [...], "hand": null}}
{"type": "command",  "text": "Put the green cube on the red cube."}
{"type": "question", "text": "Is the red cube clear?"}
```

`observe` 只发一次，且**不需要回复**（fire-and-forget）。

**被测者 → 测试者**

```json
{"type": "action", "op": "put_on", "args": ["green-cube", "red-cube"]}
{"type": "refuse", "reason": "the big red cube is not clear"}
{"type": "answer", "text": "yes"}
```

三种消息对应被测者侧的三个入口，回复就是返回值：`observe` → 无、 `question` → `answer`、`command` → `action` 或 `refuse`。

### 支持的操作（就这三个）

| 操作 | 测试者发出的英文 | 前置条件（不满足即非法，被测者应拒绝） |
| --- | --- | --- |
| `pick_up(x)` | `Pick up the red cube.` | 手为空、x 上方无物体 |
| `put_down(x)` | `Put down the red cube.` | x 正在手中 |
| `put_on(x, y)` | `Put the red cube on the blue cube.` | x≠y、**y 是 cube**（只有 cube 能支撑）、y 上方无物体 |

`put_on` **允许隐式抓取**：x 不在手中就先自动抓起来。

**句式范围**：`pick up X` / `put down X` / `put X on|onto Y`（X、Y 是名词短语）。 `Put X on the table.` 这类介词说法、`on top of`、`next to`、`in front of`、`stack`、并列谓词都在范围之外，完整清单见 `docs/设计协议.md` §3.4。

### 判分（速查）

单条指令按 2×2 表：合法且执行、非法且拒绝 = 正确；合法却拒绝、非法却执行 = 不理解。整次测试按**三段逐段判定**，段内严格、段间互不连累；第三步的基准是「测试者按被测者的调用演化出的那份状态」，因此一个操作做错不会让后面的问句失去意义。

> 规则全文见 `docs/设计协议.md` §5–§6。

### 支持的问题（就这五种）

| 题型 | 例子 | 答句 |
| --- | --- | --- |
| `attr` | `What color is the blue pyramid?` / `How big is it?` / `What shape is it?` | 颜色词 / `big`\|`small` / 形状词 |
| `rel` | `Is the green cube on the red cube?` / `Is the red cube clear?` / `Is it supported?` / `Is it on the table?` | `yes` / `no` |
| `count` | `How many cubes are on the table?` | 数字 |
| `exists` | `Is there a red cube on the table?` | `yes` / `no` |
| `all` | `Are all cubes on the table?` | `yes` / `no` |

- **属性只有三种**：颜色、大小（`big`/`small`）、形状（`cube`/`pyramid`/`ball`）。材质不做。
- **关系只有四种**：`on` / `on the table` / `clear` / `supported`。
- 名词短语形如 `the small red cube on the table`，属性可省、关系可嵌，但出题器只出**无歧义**的句子。
- **判分用的是封闭式答案**：`yes`/`no`、一个属性词、一个数字。空答、`I don't know`、整句话一律计错，协议要求必须表态。
- **五种题型之外**的（位置类、指称类、材质、比较级、自由文本、反问澄清）不做，理由见 `docs/设计协议.md` §4.6。

> 完整的判据、词表与"不支持"清单见 `docs/设计协议.md` §3–§4；上面这些表只是速查，**以协议文档和代码为准**。

---

## 扩展点

| 想做什么 | 改哪里 |
| --- | --- |
| 加一种题型 | `shrdlu/questions.py` 加语义 + 生成器 + 求值器；`shrdlu/testee/nlp.py` 加对应读法；`shrdlu/env/generator.py` 加枚举 |
| 加一个操作 | `shrdlu/ops.py` 加 `check_*` 与 `apply`；`shrdlu/env/commands.py` 加英文渲染；`shrdlu/testee/nlp.py` 加解析 |
| 加一个场景 | 手写 `shrdlu/scenarios/*.json`，或用 `shrdlu-scene` 生成到别处再指定路径 |
| 换一个被测者 | 写一个会说行协议的程序，用 `env_main --testee "python3 my_testee.py"` 接进来 |
| 提高难度层 | 场景等级只有 Level 1；扩问句协议与 `worldgen.Spec` |

---

## 设计要点（速览）

1. **测试者不提问也不解析英文**：它从语义**生成**问句，所以不需要解析器。英文理解整块落在被测者一侧，而那正是被测能力。
2. **世界的当前状态按指令推进**，不跟随被测者的行为。被测者做错指令时，世界的当前状态仍与指令要求一致；它做错的那一步只体现在 **测试者维护的被测者通过操作表现出的世界状态** 上，两份世界状态的差就是第二步的判据。
3. **判分分三段、错误不跨段传染**（见 `README.md` §4.2）。
4. **纯问答测试测的是感知，不是推理**：没有指令时初态与最终状态相同，一个永不更新模型的被测者也能满分。所以指令序列必须生成。这条以断言形式写在 `tests/test_stage7_worldgen.py`。
5. **题目分「必须推演」与「回放即可」**：前者答案在指令前后会变（或初态下无法指称）。手册场景里只有 10% 属于前者，所以题库对该比例设了下限。两轮问句之后，这两类题的差别在结果里表现为：前者只可能"第三步才答错"，后者两轮都会答对或都会答错。
6. **出题会搜索指令序列**，因为指令决定了能出多少道"必须推演"的题。先用廉价代理给全部候选打分，再只对最优的几个做精确计数。

更完整的推导见 `README.md` 与 `docs/设计协议.md`。
