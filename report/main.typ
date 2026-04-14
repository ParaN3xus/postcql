#import "data.typ": *
#import "figs.typ": *
#import "@preview/zebraw:0.6.1": *
#import "@preview/tdtr:0.5.5": *
#import "@preview/numbly:0.1.0": numbly

#set text(lang: "zh", region: "cn", font: ("Libertinus Serif", "Noto Serif CJK SC"))
#set heading(numbering: "1.")
#set document(author: "ParaN3xus")
#set par(justify: true)
#set quote(block: true)
#set table(inset: 6pt)

#show title: set align(center)
#show title: set text(1.5em)
#show quote: x => {
  block(block(x, stroke: (left: black.lighten(50%)), inset: (y: 4pt)), inset: (x: 10pt))
}

#show: zebraw


#set title("基于 CodeQL 与 LLM 的\n自主漏洞审计 Agent")
#align(center, {
  v(4.5cm)
  text(2em, "实验报告")
  title()

  v(1fr)

  "范之润"
  linebreak()
  datetime.today().display()
  v(3.5cm)
})

#pagebreak()

#set page(numbering: "1")
#outline()

#pagebreak(weak: true)

= 概述
#let target = "ImageMagick 6.9.2-10"

本实验设计并实现了一个*基于 CodeQL 与大语言模型的自主漏洞审计原型系统* "*PostCQL*", 用于*对静态分析工具输出的告警进行自动化研判*. 系统首先以 #target 为目标项目, 使用 CodeQL 的 `cpp-security-extended.qls` 套件执行扫描, 随后将得到的候选告警逐条提交给具备*源码检索*, *语义导航*和*结构化报告生成*能力的 LLM agent, 使其围绕告警位置*自动收集上下文*, *理解相关调用链*并*输出结论*.

实验结果表明, 在 #n-alerts 条 CodeQL 告警上, PostCQL 能够将原始告警集合进一步划分为 #agent-real.len() 条 `real` 与 #agent-fp.len() 条 `false_positive`, 总体判断*准确率达到 #pv(agent-accuracy)*. 与直接使用原始 CodeQL 告警相比, PostCQL 在准确率, 精确率和 F1 分数上*均有明显提升*, 说明其能够较有效地过滤噪声并降低人工分诊成本. 在结论验证阶段, 我们还确认了 4 个*上游尚未修复的真实漏洞*. 结果分析和案例研究表明, PostCQL 已经具备跨源码, 配置文件和属性展开逻辑进行上下文关联与调用链理解的能力, 但在某些场景比较复杂的告警规则上, 其结论仍然不够稳定.


= 背景与目标

静态程序分析能够在不执行目标程序的前提下, 从大规模代码中自动发现潜在缺陷, 是软件安全审计中的重要技术路线. 其中, CodeQL @ql 通过数据库化的程序表示和声明式查询对数据流, 控制流与语义关系进行分析, 已成为较有代表性的漏洞挖掘工具. 对于 C/C++ 这类语义复杂, 且容易出现内存安全与资源管理问题的语言, CodeQL *具有较高的实用价值*.

然而, 静态分析结果*通常只能提供可疑线索*, *不能等价于真实漏洞* @sa-problems. 由于规则本身需要做到健全且安全, 再加上 C/C++ 项目中大量宏, 平台分支和上下文约束的影响, 告警中往往混杂着*相当数量的假阳性*. 因此, 在实际审计中*仍需逐条阅读源码*, *理解调用链*和*边界条件*, 才能*判断告警是否成立*.

近年来, 大语言模型在*代码理解* @llm-code-understanding 和*跨文件推理* @repobench 方面展现出*较强能力*. 若将 CodeQL 提供的结构化告警信息与具备工具调用能力的 LLM agent 结合, 就有可能让 agent 围绕告警*自主*完成源码检索, 上下文收集, 路径分析和证据组织, 从而降低人工分诊成本.

基于此, 本实验设计并实现了一个基于 CodeQL 与 LLM 的自主漏洞审计 agent 原型系统 "*PostCQL*", 用于对 CodeQL 输出的告警*自动收集上下文*并*生成研判结果*. 具体而言, 本实验希望回答以下问题:
+ Agent 是否能够围绕给定告警*构建*出较完整的*分析链条*, 并给出具有*可解释*性的判断依据;
+ 在真实 C/C++ 开源项目上, 该方法能否*有效区分真实漏洞与假阳性*, 从而提升告警分诊效率;
+ "静态分析 + agent" 协同模式在实验条件下的*适用范围*, *局限性*与*后续改进方向*分别是什么.


= 系统组成

本系统的整体架构如 @fig:overall-struc 所示, 可以概括为 "CodeQL 负责*发现候选告警*, PostCQL 负责*理解上下文并完成研判*, 研判完毕后通过*提交报告固化研判结果*" 的三层流水线. 在输入侧, 目标 C++ 项目的源代码首先被构建为 CodeQL Database, 随后使用 `codeql/cpp-queries:codeql-suites/cpp-security-extended.qls` 查询套件执行扫描, 生成待处理的 CodeQL 告警集合. 这些告警提供了规则详情, 告警位置, 相关路径等关键信息, 是整个 triage 过程的起点.

在核心分析层, 系统将每个告警信息结合任务指令提交给 PostCQL. PostCQL 同时接入两类工具能力:
- 面向*源码文本*的本地函数工具, 包括 `read_source(...)` 与 `search_source(...)`, 用于快速读取代码片段, 搜索标识符和确认局部上下文;
- `mcp-language-server` 暴露出来的*语言服务器能力*, 其底层由 `clangd` 对源代码进行语义分析, 从而支持更准确的符号跳转, 引用查询和跨文件理解.

前者为 PostCQL 提供轻量直接的文本访问, 后者提供语义级代码导航, 二者共同构成 PostCQL 的外部观察能力.

#figure(
  caption: [整体架构图],
  scale(overall-struc, 80%, reflow: true),
  placement: auto,
) <fig:overall-struc>

== 核心提示词

本系统的提示词设计并非仅要求模型 "判断告警真假", 而是将其约束为一个*具备固定分析流程的漏洞审计 agent*. 除去相关工具的使用说明和一些繁琐的注意事项外, 其中的关键部分是对 PostCQL 的*审计工作流*的约束:

+ 在阅读告警位置及其附近代码后, 首先基于告警元数据和局部代码上下文, 形成一个关于 CodeQL 为何认为该位置可疑的*初始假设*;
+ 围绕这一初始假设, 检查真实程序中的周边逻辑, 包括调用者, 被调函数, 控制流, 数据流, 边界检查, 清洗逻辑与可达性, *验证该假设*是否成立;
+ 判断 CodeQL 所依赖的条件在*真实执行路径*上是否真正成立;
+ 若 CodeQL 的初始假设不成立, 也不能直接停止分析, 而是需要进一步判断代码是否仍然在*其他现实上下文*中存在风险, 以及该行为是否仍可被触发;
+ 若相关行为可以被触发, 则需要*结合具体代码证据*说明其触发条件, 执行路径, 外部输入影响, 限制条件, 潜在影响与风险成因;
+ 若相关行为在现实中不可触发, 则需要明确说明究竟是哪一处检查, 约束或不可达条件阻断了该告警.

这一工作流的核心作用, 是强制 PostCQL 先理解 CodeQL 的告警内容并建立假设, 再通过源码证据逐步验证. 对于静态分析告警而言, 真正困难的部分往往不在于理解规则字面含义, 而在于判断该规则所隐含的*前提条件*是否在目标程序的*真实路径*上成立. 因此, 提示词将 "假设 - 验证 - 修正 - 定论" 作为主线, 本质上是在让模型模仿人工审计时的基本思维过程. 完整提示词见 @sect:prompt.


== 结果提交

当定论形成时, PostCQL 将通过 `submit_triage_report` 工具提交结构化研判结果, 系统再将结果整理为最终的 Alert Triage Report 并写入产物目录. 报告中不仅包含判断结论(`real`, `false_positive` 或 `uncertain`), 还包含 CodeQL 告警原因, 验证过程, 触发路径, 影响分析与修复建议等内容.

有了详细的研判报告, 后续对 PostCQL 研判结果的人工审核和可能的修复也更加便捷.


= 实验方法

实验中使用的各种软硬件和关键配置见 @sect:exp-env.

== 目标项目选择

我们选择了 #link("https://imagemagick.org/archive/releases/ImageMagick-6.9.2-10.tar.xz", target) 为目标项目. 这一选择主要基于以下考虑:
- 为了实验的说服力, 我们决定选择*有一定影响力的开源项目*;
- 经过一些尝试, 我们发现 CodeQL 在现代 C++ 项目上表现不佳, 有时甚至不能产生任何告警. 因此我们将语言限定为 CodeQL 相对擅长的 C 语言;
- 为了能更加方便地验证 PostCQL 的输出结果, 我们决定选择历史比较悠久的项目的旧版本.

具体而言, ImageMagick 项目曾在 2016 年 5 月前后连续曝出多个高危漏洞 @imagetragick, 其开发团队在后续版本中经过多次连续修补才逐步完成修复. 这说明其代码库中*存在较多薄弱环节*, 潜在安全风险也较为丰富, 因而是开展安全分析实验的*理想样本*. 我们选择的正是这些高危漏洞集中爆发前的最后一个版本, 这样既能保留较多具有分析价值的风险代码, 也便于结合后续修复历史与公开漏洞信息对 PostCQL 的研判结果进行交叉验证.

ImageMagick 还具有较大的*工程规模*和较强的*现实影响力*. 从代码统计结果 (@fig:tokei) 来看, #target 共包含 1480 个文件, 总计约 68.99 万行, 其中 C 代码占 31.83 万行, 同时还包含大量 C Header, C++, Shell, M4, XML 与构建脚本等多种类型文件. 与此同时, ImageMagick 作为被广泛使用的图像处理库, 在开源软件生态和实际应用中具有较高影响力. 围绕该项目开展实验, 更能体现 PostCQL 在真实*复杂代码库*中的*适用性*与*实践价值*.

#figure(caption: [在 #target 源码仓库中运行代码统计工具 `tokei` 的结果], ```shell-unix-generic
$ tokei .
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 Language              Files        Lines         Code     Comments       Blanks
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 Autoconf                 48        38010        28953         5038         4019
 Automake                 12         3092         2344          359          389
 C                       263       449214       318284       106022        24908
 C Header                190        37716        26033         6277         5406
 C++                      39        17849        14119         1228         2502
 CSS                       6         1787         1606           19          162
 JavaScript                1            7            2            5            0
 M4                       28        12932         8725         3240          967
 Makefile                  1           17           16            0            1
 Perl                     26         5870         3934         1113          823
 Shell                     8        13174         9579         2294         1301
 SVG                       2           69           69            0            0
 Plain Text               13         1965            0         1413          552
 XML                      26        10122         9577          494           51
─────────────────────────────────────────────────────────────────────────────────
 HTML                    817        97963        85200           34        12729
 |- JavaScript           121          131          131            0            0
 (Total)                            98094        85331           34        12729
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 Total                  1480       689918       508572       127536        53810
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```) <fig:tokei>

== CodeQL 分析和告警研判

#target 使用 `autotools` 构建系统, 我们使用官方推荐的默认设置执行 `./configure` 配置和构建, 进而完成 CodeQL 数据库构建:

```shell-unix-generic
codeql database create work/codeql-db \
    --language=cpp \
    --source-root=work/source \
    --command="make -j$(nproc)"
```

为了获取更多结果, 我们使用 CodeQL 官方 C/C++ 套件中的 `cpp-security-extended.qls` 套件执行静态分析, 获取 CodeQL 告警结果:

```shell-unix-generic
codeql database analyze work/codeql-db \
  codeql/cpp-queries:codeql-suites/cpp-security-extended.qls \
  --format=sarifv2.1.0 \
  --output=work/results/all.sarif \
  --threads=0
```

最后, 我们启动 PostCQL, 对 CodeQL 分析结果进行研判:

```shell-unix-generic
python main.py --log-level DEBUG analyze-all
```

== 结论验证

为了构建用于结果分析的 ground truth 集合, 我们以第一次批量分析得到的结果 `work/results/analyze-all-initial` 为基础, 结合 LLM 判别与人工检验进行验证.
#figure(
  tidy-tree-graph(draw-node: tidy-tree-draws.horizontal-draw-node)[
    - 初次研判结果
      - `"real" | "uncertain"`
        - `is_valid`
          - `fixed`
            - 审阅相关 commit
          - `!fixed`
            - 使用 Report To PoC Skill 生成 PoC 并审阅
        - `!is_valid`
          - `fixed`
            - 不存在
          - `!fixed`
            - 详细审阅报告
      - `"false_positive"`
        - `is_valid`
          - `fixed`
            - 详细审阅报告
          - `!fixed`
            - 简要审阅报告
        - `!is_valid`
          - `fixed`
            - 详细审阅报告
          - `!fixed`
            - 详细审阅报告, 若有必要则生成 PoC 并审阅
  ],
  placement: auto,
  caption: [验证流水线中的人工核查决策树],
) <fig:manual-validation-flow>


由于时间有限, 我们无法对每一条告警都进行完全独立的人工复核, 因而采用了 "PostCQL 研判 - LLM 验证 - 人工检验" 的三级流水线. 具体而言, 首先由 PostCQL 对告警给出初步结论及其依据; 随后由独立的 LLM Agent (OpenAI Codex) 使用 `Report Upstream Check` skill 对该研判报告进行再次验证, 其做法是
- 将本地生成的 triage report 与上游代码仓库的最新代码和 Git 历史进行对照;
- 分别判断
  - 报告中涉及的问题是否已在后续上游版本中被修复;
  - 该报告结论本身是否成立.
最后, 再由人工对存在分歧, 结论不稳定或安全影响较大的样本进行重点核查, 以修正前两级流程中可能遗留的误判.

人工核查的具体策略取决于初次研判结果, 以及二次验证阶段给出的 `upstream_fixed` 与 `is_valid` 两项判断, 其决策流程如 @fig:manual-validation-flow 所示. 部分模糊问题的具体判定规则见 @sect:validating.


= 结果分析

`cpp-security-extended` 套件共在 #target 上输出了 #n-alerts 个告警. 基于前文所述的验证流程, 我们进一步构建了参考真值集合, 其中真实漏洞 #gt-real.len() 条, 假阳性 #gt-fp.len() 条. 从这一结果可以看出, 原始 CodeQL 输出中真实漏洞与噪声告警数量接近, 若直接依赖静态分析结果开展人工审计, 成本仍然较高.

== 总体结果

PostCQL 最终将 #agent-real.len() 条告警判为 `real`, 将 #agent-fp.len() 条告警判为 `false_positive`, 总体判断准确率为 #pv(agent-accuracy), 各个类别下的判断情况如 @fig:overall-results 所示.

#figure(
  caption: [PostCQL 研判结果在两种类别下的准确率],
  overall-results-plot,
) <fig:overall-results>

若将原始 CodeQL 告警整体视为 baseline, 则原始 CodeQL 结果与 agent 输出结果的主要分类指标对比可见 @tbl:metric-comparison.

#figure(
  caption: [原始 CodeQL 与 PostCQL 输出结果的指标对比],
  table(
    columns: 5,
    align: (left, center, center, center, center),
    stroke: none,
    table.hline(),
    table.header([*Method*], [*Accuracy*], [*Precision*], [*Recall*], [*F1*]),
    table.hline(),
    [Raw CodeQL],
    pv(codeql-baseline-accuracy),
    pv(codeql-baseline-precision),
    [-],
    pv(codeql-baseline-f1),

    [PostCQL], strong(pv(agent-accuracy)), strong(pv(agent-precision)), (pv(agent-recall)), strong(pv(agent-f1)),
    table.hline(),
  ),
) <tbl:metric-comparison>

可见, 相比直接使用原始 CodeQL 告警, PostCQL 研判结果在总体准确率, 精确率和 F1 指标上都有*明显提升*, 说明其能够较有效地过滤假阳性并提高后续人工审计效率.

此外, 结合结论验证时获得的 `upstream_fixed` 结果, 我们确认了 4 个由初版 PostCQL 发现且*上游尚未修复的真实漏洞*, 详情见 @sect:new-bugs.


== 不同告警类型上的表现差异

从规则分布上看, 本次实验中的告警主要集中在 `cpp/path-injection` (#rule-count("cpp/path-injection") 条) 与 `cpp/integer-multiplication-cast-to-long` (#rule-count("cpp/integer-multiplication-cast-to-long") 条) 两类, 其余规则数量都较少. 这意味着系统整体效果在很大程度上取决于 PostCQL 对这两类高频规则的处理能力.

进一步按规则类型观察, PostCQL 在不同类型上的表现差异较为明显. 对于 `cpp/integer-multiplication-cast-to-long`, PostCQL 的判断准确率达到 #pv(rule-accuracy("cpp/integer-multiplication-cast-to-long")), 表现相对稳定; 而对于 `cpp/path-injection`, 准确率仅为 #pv(rule-accuracy("cpp/path-injection")), 明显更难处理. 这一差异说明, 当告警对应的是较局部, 语义模式较固定的整数运算问题时, PostCQL 更容易围绕表达式类型, 运算宽度和边界检查形成稳定判断; 相比之下, 路径注入类告警往往依赖*跨函数的数据流恢复*, *调用上下文分析*以及对 "用户可控" 与 "程序内部构造" 之间*边界的准确把握*, 因而更*容易引发误判*.

不同规则的样本占比以及对应的判断准确率如 @fig:rule-performance 所示.

#figure(
  caption: [不同告警规则的分布及其判断准确率],
  rule-acc-pie,
) <fig:rule-performance>

== 案例分析

=== 成功案例: 225 号告警

一个较典型的成功样例是第 225 号告警, 对应 `cpp/uncontrolled-process-operation` 规则在 `magick/delegate.c:406` 附近的 `system()` 调用. 这一位置本身就是 ImageTragick 系列漏洞 @imagetragick 在代码中的关键执行点之一: 经属性展开后的 delegate 命令最终在这里进入 shell 执行.

在这一样例中, PostCQL 首先使用本地源码工具和 LSP 收集了大量与告警点相关的上下文信息, 在随后的思考中, PostCQL *准确地抓住*了用于过滤命令的 `sanitize` 函数这个*关键点*:


#quote[
  I need to gather enough information to make a decision about whether to compile the configuration. *It's important to understand if sanitization is sufficient or if the user could inject shell metacharacters, especially since the whitelist includes some dangerous characters*. I'll trace the path from command-line arguments to the system and check if the command involves...
]

随后, PostCQL 调用工具在关键文件 `delegates.xml.in` (ImageMagick 的外部程序调用配置) 中进行了大量的搜索和读取, 以寻找危险配置:

```json
{
  "event_type": "tool_called",
  "details": {
    "tool_name": "search_source_text",
    "arguments": "{\"glob_pattern\":\"config/delegates.xml.in\",\"page_offset\":0,\"page_size\":40,\"pattern\":\"%i\"}",
    "call_id": "call_qPE5BeoWj5EANQCWroQhsHOr"
  }
}
```

这些思考和工具调用展示了 PostCQL 良好的自动进行*上下文关联*, *理解调用链*并*综合多源证据*完成漏洞研判的能力. 最终, 在提交的报告中, PostCQL 将该告警判别为真实漏洞, 并正确给出了这一漏洞的触发路径.

#figure(
  range(7, 10).map(x => image(result-dir + "225/report.pdf", width: 5cm, page: x)).map(box).join(),
  caption: [225 号告警研判报告部分内容],
)

=== 失败案例: 197 号告警

与之相对, 一个典型的失败样例是第 197 号告警, 对应总体准确率较低的 `cpp/path-injection` 规则在 `magick/delegate.c:1328` 附近对 `RelinquishUniqueFileResource(image_info->filename)` 的调用. 这一样例同样位于 delegate 执行路径上, 与前面的成功案例处于相近的上下文, 但 PostCQL 最终却将其误判为 `false_positive`. 在这一样例中, PostCQL 同样进行了较充分的上下文收集: 它既读取了 `delegate.c` 中告警点附近的大段源码, 也追踪了 `AcquireUniqueFilename`, `RelinquishUniqueFileResource` 和 `CopyDelegateFile` 等辅助函数, 还专门检查了 `image_info->filename` 在 `InvokeDelegate` 中的保存, 改写与恢复过程. 从过程上看, 这些工具调用说明 PostCQL *已经在试图*将告警放回软件*完整的工作流*中理解.

基于这一路径追踪, PostCQL 最终认为 `image_info->filename` 在到达第 1328 行之前已经被 `AcquireUniqueSymbolicLink` 和 `AcquireUniqueFilename` 改写成了库内部生成的临时路径, 因而此处只是在清理 delegate 调用中的临时文件, 并不对应真实的路径注入问题.

这一分析在局部上并非毫无道理, 因为*大多数* delegate 的确会保存原始路径, 再把 `image_info->filename` 重写为临时工作路径, 但 `SCAN` 恰好跳过了这一步, 所以 `image->filename` 仍然是用户原始输入. 也就是说, PostCQL 在这一案例中虽然*成功重建了局部上下文*和*一般情况下的代码执行路径*, 但却在收敛结论时产生了某种局部幻觉: 它把对常见路径的合理解释推广成了对整体行为的判断, 从而*遗漏*了少数情况下的*特殊执行路径*, 最终把真实问题误判成了假阳性.

这一失败样例说明, PostCQL 在面对这类多情景问题时, 虽然已经能够主动扩展上下文, 理解字段保存, 改写和恢复之间的关系, 但仍然可能*陷入某个局部解释*, 而*忽略*某些*特殊执行路径*上的实际危险性. 一种可能的改进方向, 是进一步借助 LSP 提供的语义导航能力以及过程化的 case 遍历一类外部工具, 将 "哪些分支会改写字段, 哪些分支会恢复字段, 哪些分支保留原始输入" 显式展开为更严格的分类讨论过程, 从而减少模型在中间推理中因过早概括而产生的遗漏.

== 局限性

=== 判断能力不够稳定

综合前文的统计结果与案例分析可以看出, 本系统当前的局限性并不主要在于无法理解单条告警的字面含义, 而在于面对复杂上下文时, 仍然难以稳定地区分 "代码语义相关" 与 "真实漏洞" 这两个层次. 对于第 225 号告警这类需要跨越源码, 配置文件和属性展开逻辑进行综合判断的问题, PostCQL 已经能够较好地建立*完整的分析链条*; 但对于 `cpp/path-injection` 这类强依赖路径可控性, 状态更新顺序和特殊执行分支的规则, 其最终结论仍然容易受到*局部代码模式的干扰*.

从不同规则类型上的表现差异也可以看出这一点. 对于模式较明确, 关键证据集中在少量表达式和调用点上的告警, PostCQL 往往可以较稳定地完成研判; 而一旦问题涉及临时文件生命周期, delegate 工作流, 或者字段在不同控制流分支中的多次改写与恢复, PostCQL 就更容易把一般情况下成立的局部解释错误地推广到整个程序路径上. 换言之, 它已经具备了较强的自动上下文关联能力, 但在把这些上下文进一步提炼为最终安全结论时, 仍然*缺乏足够稳定的边界判断能力*.

此外, 当前系统虽然要求 PostCQL 在提交最终报告时按照预设工作流组织结论, 但从部分失败案例来看, 模型在实际调查过程中并不总是严格遵循这一分析路径. 这说明现有约束更多作用于*结果表达*, 而不是对中间检索, 假设验证和结论收敛过程形成持续控制; 一旦模型过早接受某个局部解释, 后续调查就可能偏离原本希望执行的验证步骤. 后续可以考虑通过进一步强化提示词约束, 或引入阶段性报告, 中间检查点等外部机制, 使 PostCQL 更稳定地按照预设流程逐步收集证据, 验证关键假设并完成结论收敛.

=== 效率较低

除了结论质量之外, 系统在分析效率上也仍有明显的提升空间. 当前实现将每条告警独立处理, 因而 PostCQL 会围绕每一条告警重新收集上下文, 重新阅读相似代码, 甚至*重复分析*同一条调用链上的多个不同告警点. 但在实际结果中可以看到, 许多告警本质上只是同一问题在不同调用点或不同 sink 上的重复, 完全可以在更高层次上*合并处理*.

此外, 对于同一个项目中的多条告警, 系统也完全可以预先建立关于项目架构, 关键模块职责以及内部工作流的*共享上下文*, 让后续 PostCQL 在分析具体告警时直接复用这些信息, 从而减少重复工具调用和重复推理带来的成本.

= 总结

本实验围绕 "静态分析 + LLM agent" 的协同漏洞研判流程, 设计并实现了自主漏洞审计原型系统 "*PostCQL*". 系统以 CodeQL 告警为输入, 结合本地源码检索工具, 基于 `clangd` 的语言服务器能力以及结构化报告提交机制, 实现了对单条告警的自动上下文收集, 路径分析与初步定性. 在 #target 上的实验结果表明, PostCQL 能够在*保持较高召回能力*的同时显著*提升告警分诊质量*, 并进一步确认了 4 个上游尚未修复的真实漏洞.

从结果分析和案例研究可以看出, PostCQL 已经能够围绕单条告警建立较完整的分析链条, 并给出具有可追溯性的判断依据. 特别是在 225 号告警这样的成功样例中, PostCQL 不仅能沿着源码中的*关键调用*继续追踪, 还能够结合 `delegates.xml` 等*配置元信息*进行综合判断, 说明这种基于工具调用的 agent 已经具备了一定的*自动上下文关联*与*调用链理解能力*.

在真实项目上的整体效果同样表明, "静态分析 + agent" 的协同方式具有明确的实用价值. 相比直接使用原始 CodeQL 告警, PostCQL 在准确率, 精确率和 F1 指标上均有明显提升, 说明它确实能够承担告警降噪和初步分诊的工作, 将人工审计资源更集中地引导到高价值样本上. 与此同时, 不同类型告警之间仍存在明显差异: 对*模式相对固定*, *风险链条较清晰*的问题, PostCQL 往往更*容易形成稳定结论*; 而对 `cpp/path-injection` 这类关于依赖路径可控性, *特殊执行分支*和*细粒度语义边界判断*的规则, 其判断仍然*存在波动*.

另一方面, 本实验也暴露出当前系统在稳定性与效率上的改进空间. 后续若能在*共享上下文缓存*, *同链路告警合并*和*复杂上下文告警判别*等方向进一步完善, 这一协同流程仍有望取得*更稳定且更高效*的效果.


#{
  set text(lang: "en", region: "us")
  bibliography("ref.bib")
}

#pagebreak(weak: true)
#counter(heading).update(0)
#set heading(numbering: x => "附录" + str(x) + ".")

#set heading(numbering: numbly(
  "附录 {1}.",
  "{1}.{2}.",
))

= 实验环境和配置 <sect:exp-env>

#figure(
  table(
    columns: 2,
    align: (center + horizon, center),
    stroke: none,
    table.hline(),
    table.header([*类别*], [*型号*]),
    table.hline(),
    [CPU], [Intel(R) Xeon(R) CPU E5-2698 v4 @ 2.20GHz],
    [RAM], [8 × 32GB DDR4 2400MT/s, \ Samsung (M393A4K40BB1-CRC)],
    table.hline(),
  ),
  caption: [实验平台部分关键硬件配置],
)

#figure(
  table(
    columns: 2,
    align: (center + horizon, center),
    stroke: none,
    table.hline(),
    table.header([*软件*], [*版本*]),
    table.hline(),
    [CodeQL CLI], [2.25.1],
    [codeql/cpp-queries], [1.5.15],
    [clangd], [Debian clangd version 19.1.7 (3+b1)],
    [gcc], [gcc-14 (Debian 14.2.0-19) 14.2.0],
    [python], [Python 3.14.2],
    [ImageMagick], [6.9.2-10],
    table.hline(),
  ),
  caption: [实验中所用的关键软件版本],
)

#figure(
  table(
    columns: 2,
    align: (center + horizon, center),
    stroke: none,
    table.hline(),
    table.header([*配置项*], [*值*]),
    table.hline(),
    [`model`], [`gpt-5.4` #footnote[使用第三方代理站点 https://fastai.fast 提供的 API]],
    [`max_turns`], [`128`],
    [`reasoning_effort`], [`medium`],
    table.hline(),
  ),
  caption: [实验中所用的关键参数配置],
)


= 部分模糊问题的判定规则 <sect:validating>
- 使用 `sscanf` 读取格式化字符串, 在无害的使用垃圾值后再格式检查并退出: \ 真实漏洞. 尽管该问题作为漏洞被利用的概率微乎其微, 但让该概率降低为 0 的正确做法是显而易见且可以被轻易达成的. 无论何时, 我们当然希望软件有尽量少的弱点, 何况改正这个问题并没有多少代价. 因此我们决定将该问题视为真实漏洞.
- 允许用户自定义临时文件目录, 且在 `mkstemp` 后又使用 `open` 等函数打开临时文件: \
  真实漏洞. 这样做显然是违背安全的临时文件使用实践的. 理想情况下我们应该只使用 `fd` 而不是创建临时文件后又重新按路径打开. 这样的做法大大降低了 `mkstemp` 的安全价值, 理应视为真实漏洞.

= PostCQL 发现的新漏洞 <sect:new-bugs>

== 64 号告警: 数值溢出导致输出损坏
ImageMagick 在执行 `-morphology Convolve` 时允许用户提供任意卷积核系数. 对于 `CMYK` 图像, 其在卷积路径中会将用户提供的 kernel 系数与 alpha 权重相乘, 再参与黑色通道的计算. 当系数大到超出当前数值类型可稳定表示的范围时, 中间结果会进入异常数值状态, 最终导致输出像素被错误饱和. PoC 如下

```shell-unix-generic
$ printf '%b' 'id=ImageMagick  version=1.0\nclass=DirectClass  colors=0  matte=False\ncolumns=1  rows=1  depth=16\ncolorspace=CMYK\npage=1x1+0+0\nrendering-intent=Perceptual\ngamma=0.454545\nred-primary=0.64,0.33  green-primary=0.3,0.6  blue-primary=0.15,0.06\nwhite-point=0.3127,0.329\n\f\n:\x1a\x00\x00\x00\x00\x00\x00\x80\x00' > base-cmyk.miff && identify -verbose base-cmyk.miff | grep -A6 'Black:' && convert base-cmyk.miff -morphology Convolve '1:1' out-normal.miff && identify -verbose out-normal.miff | grep -A6 'Black:' && convert base-cmyk.miff -morphology Convolve '1:1e39' out-huge.miff && identify -verbose out-huge.miff | grep -A6 'Black:'
    Black:
      min: 32768 (0.500008)
      max: 32768 (0.500008)
      mean: 32768 (0.500008)
      standard deviation: 0 (0)
      kurtosis: 0
      skewness: 0
    Black:
      min: 32768 (0.500008)
      max: 32768 (0.500008)
      mean: 32768 (0.500008)
      standard deviation: 0 (0)
      kurtosis: 0
      skewness: 0
    Black:
      min: 65535 (1)
      max: 65535 (1)
      mean: 65535 (1)
      standard deviation: 0 (0)
      kurtosis: 0
      skewness: 0
```

可以看到, 对同一个 `1x1` `CMYK` 输入图像, 正常卷积核 `1:1` 会保持黑色通道为 `32768`, 而过大的卷积核 `1:1e39` 会导致黑色通道错误地变为 `65535`. 证明漏洞存在.


== 86 号告警: 越界读取
ImageMagick 的公开 XML tree API `AddChildToXMLTree` 允许调用者传入任意 `offset`, 但 `InsertTagIntoXMLTree` 在插入子节点时并不会校验该 `offset` 是否超出父节点内容长度. 当后续调用 `XMLTreeInfoToXML` 序列化 XML tree 时, 这个未校验的偏移将导致对父节点内容的越界读取. PoC 如下

```c
#include <stdio.h>
#include <stdlib.h>

#include "magick/MagickCore.h"
#include "magick/xml-tree.h"

int main(int argc, char **argv)
{
  const size_t offset = (argc > 1) ? strtoull(argv[1], NULL, 0) : (size_t) 0x40000000ULL;
  XMLTreeInfo *root;
  XMLTreeInfo *child;
  char *xml;

  MagickCoreGenesis(argv[0], MagickFalse);

  root = NewXMLTreeTag("root");
  if (root == (XMLTreeInfo *) NULL)
    {
      fprintf(stderr, "failed: NewXMLTreeTag(root)\n");
      return 2;
    }
  if (SetXMLTreeContent(root, "A") == (XMLTreeInfo *) NULL)
    {
      fprintf(stderr, "failed: SetXMLTreeContent(root)\n");
      DestroyXMLTree(root);
      return 2;
    }

  child = AddChildToXMLTree(root, "child", offset);
  if (child == (XMLTreeInfo *) NULL)
    {
      fprintf(stderr, "failed: AddChildToXMLTree(child, offset=%zu)\n", offset);
      DestroyXMLTree(root);
      return 2;
    }
  if (SetXMLTreeContent(child, "B") == (XMLTreeInfo *) NULL)
    {
      fprintf(stderr, "failed: SetXMLTreeContent(child)\n");
      DestroyXMLTree(root);
      return 2;
    }

  fprintf(stderr,
    "[*] serializing tree with parent content length 1 and child offset %zu\n",
    offset);
  xml = XMLTreeInfoToXML(root);
  if (xml == (char *) NULL)
    {
      fprintf(stderr, "[*] XMLTreeInfoToXML returned NULL\n");
      DestroyXMLTree(root);
      MagickCoreTerminus();
      return 1;
    }

  printf("%s\n", xml);
  xml = DestroyString(xml);
  DestroyXMLTree(root);
  MagickCoreTerminus();
  return 0;
}
```

将此程序编译为 `poc` 并执行
```shell-unix-generic
$ ./poc 999999
[*] serializing tree with parent content length 1 and child offset 999999
[1]    2054690 segmentation fault  ./xml-tree-offset-poc 999999
```
执行后, 程序在 `XMLTreeInfoToXML` 序列化阶段发生崩溃, 证明漏洞存在.


== 88, 89 号告警: 使用未初始化的变量
ImageMagick 在解析 txt 格式时使用了 `sscanf` 来读取格式化的坐标文本, 然而其在告警处未经格式检查就使用了 `sscanf` 读取的坐标. 大多数情况下, 该瑕疵会被后续的 `GetAuthenticPixels` 检查到并输出 `pixels are not authentic` 警告; 少数情况下, 未清理的旧栈值会导致错误的像素被修改. PoC 如下

```shell-unix-generic
$ printf '# ImageMagick pixel enumeration: 2,1,255,srgb\n0,0: (1,0,0)\nBOOM%%\n' > txt-uninit-coords-poc.txt && convert txt:txt-uninit-coords-poc.txt txt:-

convert: UnableToOpenConfigureFile `colors.xml' @ warning/configure.c/GetConfigureOptions/706.
# ImageMagick pixel enumeration: 2,1,255,srgb
0,0: (771,0,0)  #030000  srgb(3,0,0)
1,0: (65535,65535,65535)  #FFFFFF  white
```

可以看到 `0,0` 处的像素被错误修改为 `srgb(3,0,0)`, 证明漏洞存在.

```shell-unix-generic
$ printf '# ImageMagick pixel enumeration: 2,1,255,srgb\nBOOM%%\n' > txt-uninit-coords-poc.txt && convert txt:txt-uninit-coords-poc.txt txt:-

convert: pixels are not authentic `txt-uninit-coords-poc.txt' @ error/cache.c/QueueAuthenticPixelCacheNexus/4017.
# ImageMagick pixel enumeration: 2,1,255,srgb
0,0: (65535,65535,65535)  #FFFFFF  white
1,0: (65535,65535,65535)  #FFFFFF  white
```

可以看到输出了 `pixels are not authentic` 警告, 证明漏洞存在.


== 169 号告警: 意外文件删除
当 ImageMagick 的 `convert` 命令把结果写到类似 `tiff:-` 这样的非 seekable 输出时, 在清理阶段错误地把原始逻辑输出名 `-` 当成真实文件路径删除. PoC 如下

```shell-unix-generic
$ printf 'sentinel\n' >"-" && printf 'P3\n1 1\n255\n255 0 0\n' > nonseekable-output-delete-input.ppm && ls - -l && convert nonseekable-output-delete-input.ppm tiff:- | cat >/dev/null; test -e - && ls - || echo deleted

-rw-rw-r-- 1 admin admin 9 Apr 13 15:06 -
deleted
```

执行后, 命令最开始创建的哨兵文件 `-` 被删除, 证明漏洞存在.


= 提示词模板全文 <sect:prompt>

```md
You are triaging one CodeQL finding against a real C/C++ codebase.

Primary requirements:
- Use MCP language-server tools aggressively, and prefer position-based queries first.
- Use the local read_source_context tool whenever you need exact source text.
- Use read_source_span when you already know the exact range to inspect.
- Use search_source_text for grep-like repository text search.
- Use search_source_files to locate candidate files by filename/path.
- Some local source tools support pagination. Prefer small pages first and only
  request additional pages when the prior result indicates more content is needed.
- Start from the alert location using hover, diagnostics, references,
  and any other relevant tools.
- Think through the problem step by step before concluding.
- Determine whether the CodeQL alert is REAL, FALSE_POSITIVE, or UNCERTAIN.
- Classification rule: REAL does not require a high-severity security impact.
  If the condition or bug CodeQL identified actually occurs in the real code
  path and is realistically triggerable, classify it as REAL even when the
  impact is only low severity, reliability-only, or otherwise not a strong
  security vulnerability.
- Classification rule: do not treat unavoidable program semantics as a real
  vulnerability when the reported flow is simply the intended feature needed
  for the program to operate. For example, if a command-line tool must open a
  user-specified input file to do its job, a user-controlled path reaching
  `open` is not by itself a real vulnerability unless additional code evidence
  shows unsafe behavior beyond that expected feature boundary.
- Classification rule: some non-best-practice patterns are still REAL when
  they create a meaningful security risk even if the bug looks subtle or
  low-level. For example, creating a temporary file with `mkstemp` but then
  failing to manage the returned file descriptor safely, or reopening the path
  later instead of consistently using the original descriptor, should be
  treated as REAL when the surrounding code makes the resulting race or file
  safety issue realistic.
- Classification rule: treat temporary-file lifecycle regressions as REAL by
  default when code first establishes a temporary file or temporary pathname in
  a safer way, but later falls back to pathname-based handling of that same
  artifact. Typical signals include losing the original descriptor or handle,
  passing the temp pathname through additional subsystems, or reusing the temp
  pathname for later reads, writes, delegate execution, or cleanup. Do not
  dismiss these cases merely because the pathname is library-generated rather
  than copied directly from user input.
- Classification rule: when an alert lands on a cleanup or follow-up operation
  involving a temporary artifact, analyze the whole temporary-file lifecycle
  rather than only the sink line. If nearby code shows that the same temp
  artifact was later reused through pathname semantics, related cleanup
  findings should normally follow the same verdict as that underlying
  temporary-file handling issue.
- Classification rule: avoid line-local reasoning for temporary resources. A
  cleanup sink is not automatically safe just because it deletes a
  library-generated temp path; if the surrounding lifecycle for that same temp
  artifact already regressed to less-safe pathname-based handling, classify the
  cleanup finding consistently with that broader issue unless the code shows it
  is a different artifact or a different control-flow path.
- Classification rule: do not break the temporary-file lifecycle just because
  the temp path is wrapped inside another object or string representation
  before later use. If code writes or creates a temp artifact and then passes
  that artifact into another API by embedding the pathname into a cloned info
  struct, a format-prefixed filename string, a delegate command, or another
  derived wrapper, that still counts as later pathname-based reuse of the same
  temp artifact.
- Classification rule: do not over-index on style-only or hygiene-only issues.
  If a pattern is merely non-ideal but the code evidence does not show a
  realistic security consequence, classify it as FALSE_POSITIVE rather than
  treating every non-best-practice as a real vulnerability.
- Classification rule: use FALSE_POSITIVE when the CodeQL-implied condition
  does not actually hold on the real path, or is blocked by guards,
  sanitization, type/range constraints, or missing reachability.
- Classification rule: use UNCERTAIN when the available code evidence is not
  strong enough to decide between REAL and FALSE_POSITIVE.
- Classification rule: when macro-controlled code makes the real behavior
  ambiguous, treat the effective build configuration in `compile_commands.json`
  as the source of truth for which macros and paths actually apply.
- Be explicit about uncertainty.
  Do not claim exploitability unless the code evidence supports it.
- If you need to reason about control flow or data flow, use the available
  code navigation tools to gather evidence before concluding.

Required analysis process:
1. After reading the alert location and nearby code, form an initial hypothesis
   for why CodeQL treated this location as suspicious, using the alert metadata
   and local code context.
2. Validate that hypothesis against the actual program behavior by checking
   surrounding logic, callers, callees, guards, sanitization, data flow,
   control flow, and reachability.
3. Decide whether the condition CodeQL appears to rely on actually holds in the
   real code path.
4. If that CodeQL-based hypothesis does not hold, do not stop there. Evaluate
   whether the code is still unsafe in some other realistic context, and whether
   the behavior can still be triggered.
5. If the behavior is triggerable, explain why with concrete code evidence,
   including the relevant execution path, attacker or input influence, limiting
   conditions, likely impact, severity, and the deeper semantic reason the code
   is unsafe.
6. If the behavior is not realistically triggerable, explain exactly what
   blocks it.

CodeQL finding:
- row_index: {}
- rule_name: {}
- severity: {}
- file: {}
- start_line: {}
- start_column: {}
- end_line: {}
- end_column: {}
- rule_description: {}
- rule_full_description: {}
- rule_precision: {}
- rule_problem_severity: {}
- rule_security_severity: {}
- alert_message: {}

CodeQL related locations:
{}

CodeQL code flows:
{}

The final tool submission must include:
- verdict: REAL, FALSE_POSITIVE, or UNCERTAIN
- severity: low, medium, high, or critical
- explanation
- initial_hypothesis
- hypothesis_validation: a list of validation steps; each step must have a
  message and may optionally include evidence locations
- triggerability
- trigger_path: a list of concrete path steps with file/line info and message
- impact
- remediation

Keep the answer technical and specific to the codebase.

Final submission requirement:
- Do not return a free-form final answer.
- When your investigation is complete, call submit_triage_report exactly once.
- `explanation`, `initial_hypothesis`, and `triggerability` are always required.
- `hypothesis_validation` is always required and should normally be a structured
  sequence of validation steps. Each step must contain a clear conclusion in
  prose, and may optionally attach one or more code evidence locations. Use
  `none` only if you genuinely could not obtain enough code evidence to validate
  the hypothesis.
- `trigger_path` may be `none` when the behavior is not realistically
  triggerable, when the verdict is FALSE_POSITIVE, or when the evidence is too
  incomplete to claim a concrete execution path.
- `impact` may be `none` when there is no realistic attacker-reachable unsafe
  behavior to describe.
- `remediation` may be `none` when there is no concrete vulnerability to fix,
  such as a clear FALSE_POSITIVE with no underlying bug.
- Do not use `none` for convenience. Only use it when the field is genuinely
  not applicable to the final verdict or unsupported by the code evidence.
- hypothesis_validation must be a structured sequence of validation steps, not
  one free-form paragraph.
- Use hypothesis_validation to prove or disprove the initial hypothesis directly
  from the code. For false positives, show the exact guards, missing reachability,
  or contradictory call-flow evidence that blocks the issue. Not every step
  needs an attached code location, but attach evidence where it materially
  strengthens the claim.
- Any `file_path` attached in `hypothesis_validation.evidence` or `trigger_path`
  must be a source-relative repository path such as `magick/utility.c`, never
  an absolute filesystem path.
- Any attached source range must refer to a real file and valid 1-based line
  numbers within that file. Do not invent ranges that extend past the file's
  actual line count.
- Keep verdict and triggerability logically consistent. Do not mark a finding
  FALSE_POSITIVE if your analysis says the CodeQL-identified condition really
  happens and is triggerable; in that case classify it as REAL and describe the
  actual impact level separately.
- trigger_path must be a structured sequence of path steps, not one free-form paragraph.
- These fields are rendered directly as section content under Markdown headings in
  the final report. Write them as clean prose paragraphs or structured steps,
  not as `Field Name: value` labels.
- Use normal sentence casing and paragraph formatting. Start sentences with a
  capital letter, and do not prefix the body text with redundant item names such
  as `Explanation:` or `Impact:`.
```
