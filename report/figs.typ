#import "data.typ": alerts, fp-correct-ratio, fp-fp, gt-fp, gt-real, pv, real-correct-ratio, real-real
#import "@preview/cetz:0.4.2": canvas
#import "@preview/cetz-plot:0.1.3": chart
#import "@preview/fletcher:0.5.8" as fletcher: diagram, edge, node
#import "@preview/lilaq:0.6.0" as lq

#let slate = rgb("#5F766F")
#let teal-soft = rgb("#7F9C94")
#let teal-pale = rgb("#C9D8D4")
#let sand = rgb("#D39A6A")
#let sand-soft = rgb("#E8C7A6")
#let clay = rgb("#B97B66")
#let sage = rgb("#8EA476")
#let stone = rgb("#D7D1C7")
#let ink-soft = rgb("#5C5A57")

#let chart-primary = teal-soft
#let chart-secondary = slate
#let chart-agent = sage
#let chart-accent = sand
#let chart-output = sand
#let chart-accent-3 = clay
#let chart-accent-4 = sage
#let chart-muted = stone

#let overall-struc = move(dx: 0.8cm, diagram(
  // debug: true,
  node-corner-radius: 4pt,
  {
    let tint(c) = (stroke: c, fill: rgb(..c.components().slice(0, 3), 5%), inset: 8pt)

    node(
      (0, 0),
      height: 3cm,
      width: 4cm,
      align(top, [
        Source Code
        #image("assets/image-magick.svg", width: 1.6cm)
      ]),
      shape: rect,
      ..tint(chart-primary),
      name: <src>,
    )
    edge(<src>, <cqldb>, "->", image("assets/ql.svg", width: 0.5cm))
    node(
      (1, 0),
      height: 3cm,
      width: 4.2cm,
      align(top, {
        [CodeQL Database]
        image("assets/codeql.png", width: 1.5cm)
      }),
      shape: rect,
      ..tint(chart-secondary),
      name: <cqldb>,
    )
    edge(
      <cqldb>,
      <alerts>,
      "->",
      {
        align(center, {
          image("assets/ql.svg", width: 0.5cm)
          text(0.7em, `cpp-security-extended`)
          v(0.8em)
        })
      },
      label-fill: false,
      label-side: center,
    )
    node(
      (2, 0),
      height: 3cm,
      align(top, {
        [CodeQL Alerts]
        v(-5pt)
        stack(
          dir: ttb,
          spacing: 5pt,
          ..(
            rect(radius: 4pt, height: 10pt, width: 100%, ..tint(chart-secondary.lighten(12%)), {
              move(dy: -9pt, "...")
            }),
          )
            * 4,
        )
      }),
      shape: rect,
      ..tint(chart-secondary),
      name: <alerts>,
    )

    node(
      (2, 1),
      height: 2.8cm,
      defocus: -2569,
      shape: rect,
      ..tint(chart-agent),
      {
        `agents.Agent`
        image("assets/chatgpt.svg", width: 1cm)
      },
      name: <agent>,
    )

    node(
      (2, 2),
      height: 2.8cm,
      { box(width: 6cm) },
    )
    node(
      (rel: (0mm, 10mm), to: (1, 1)),
      width: 4.2cm,
      shape: rect,
      ..tint(chart-agent),
      `read_source(...)`,
      name: <readsrc>,
    )
    node(
      (rel: (0mm, 0mm), to: (1, 1)),
      width: 4.2cm,
      shape: rect,
      ..tint(chart-agent),
      `search_source(...)`,
      name: <searchsrc>,
    )
    node(
      (rel: (0mm, -10mm), to: (1, 1)),
      width: 4.2cm,
      shape: rect,
      ..tint(chart-agent),
      `mcp-language-server`,
      name: <mcp>,
    )

    node(
      (rel: (0mm, -10mm), to: (0, 1)),
      shape: rect,
      ..tint(chart-secondary),
      `clangd`,
      name: <lsp>,
    )
    edge(<src>, <lsp>, "->")
    edge(<src>, <readsrc>, "->", corner: left)
    edge(<src>, <searchsrc>, "->", corner: left)
    edge(<lsp>, <mcp>, "->")

    edge(<readsrc>, (rel: (0mm, 10mm), to: <agent>), "->")
    edge(<searchsrc>, <agent>, "->")
    edge(<mcp>, (rel: (0mm, -10mm), to: <agent>), "->")

    edge(<alerts>, <agent>, "->")

    node(
      (1, 2),
      width: 4.2cm,
      [
        `submit_triage_report`
      ],
      shape: rect,
      ..tint(chart-agent),
      name: <submit>,
    )
    edge(<agent>, <submit>, "->", corner: right)

    node(
      (0, 2),
      width: 4cm,
      align(center, {
        [Alert Triage Reports]
        range(7)
          .map(x => {
            place(
              dx: (-x) * -0.3cm + 0.3cm,
              dy: (20 - x) * 0.02cm,
              box(fill: white, image("assets/example-report.pdf", width: 1cm, page: (10 - x))),
            )
          })
          .join()
        v(1.8cm)
      }),
      shape: rect,
      ..tint(chart-output),
      name: <report>,
    )
    edge(<submit>, <report>, "->")
  },
))

#let rule-acc-pie = {
  let rule-count(name) = alerts.filter(a => a.at("rule-name") == name).len()
  let rule-correct(name) = alerts.filter(a => a.at("rule-name") == name and a.at("verdict") == a.at("gt-verdict")).len()
  let rule-accuracy(name) = 1.0 * rule-correct(name) / rule-count(name)

  let short-rule-label(name) = {
    if name == "cpp/path-injection" {
      [Path Injection]
    } else if name == "cpp/integer-multiplication-cast-to-long" {
      [`int` Multiplication Cast]
    } else if name == "cpp/missing-check-scanf" {
      [Missing `scanf` Check]
    } else if name == "cpp/uncontrolled-process-operation" {
      [Uncontrolled Process Op]
    } else {
      name
    }
  }

  let rule-summaries = alerts
    .map(a => a.at("rule-name"))
    .dedup()
    .map(name => (
      name: name,
      count: rule-count(name),
      accuracy: rule-accuracy(name),
      short-label: short-rule-label(name),
    ))
    .sorted(key: item => item.count)
    .rev()

  let top-rule-summaries = rule-summaries.slice(0, 2)
  let other-rule-summaries = rule-summaries.slice(2)
  let other-rule-count = other-rule-summaries.map(item => item.count).sum()
  let other-rule-correct = other-rule-summaries.map(item => item.count * item.accuracy).sum()
  let other-rule-accuracy = if other-rule-count == 0 {
    0.0
  } else {
    other-rule-correct / other-rule-count
  }

  let rule-pie-data = (
    ..top-rule-summaries.map(item => (
      align(center + horizon)[
        #item.short-label
        #linebreak()
        #item.count alerts, #pv(item.accuracy) acc.
      ],
      item.count,
    )),
    if other-rule-count > 0 {
      (
        align(center + horizon, [
          Other
          #linebreak()
          #other-rule-count alerts, #pv(other-rule-accuracy) acc.
          #v(-64pt)
        ]),
        other-rule-count,
      )
    },
  )

  v(-40pt)
  canvas({
    let colors = (
      chart-primary,
      chart-accent,
      chart-muted,
      chart-accent-3,
      chart-agent,
    )

    chart.piechart(
      rule-pie-data,
      value-key: 1,
      label-key: 0,
      radius: 2,
      inner-radius: 0,
      stroke: none,
      slice-style: colors,
      inner-label: (content: "%", radius: 100%),
      outer-label: (content: "LABEL", radius: 200%),
      legend: (label: none),
    )
  })
}

#let overall-results-plot = {
  lq.diagram(
    xaxis: (
      lim: (-0.6, 1.6),
      ticks: ([Real], [False Positive]).enumerate(),
      label: [Alert Class],
      subticks: none,
    ),
    yaxis: (lim: (0, 144), label: [Alert Count]),
    legend: (position: top + left, dx: 100%),
    ..{
      let group-w = 0.52
      let gt-fill = chart-primary
      let correct-fill = chart-accent
      let wrong-fill = chart-muted
      let pct-label(value, fill: black) = text(0.75em, fill: fill, strong(pv(value)))

      (
        lq.bar(
          range(2),
          (gt-real.len(), gt-fp.len()),
          offset: -group-w / 4,
          width: group-w / 2,
          fill: gt-fill,
          label: [Ground Truth],
        ),
        lq.bar(
          range(2),
          (gt-real.len(), gt-fp.len()),
          base: (real-real.len(), fp-fp.len()),
          offset: group-w / 4,
          width: group-w / 2,
          fill: wrong-fill,
          label: [PostCQL Incorrect],
        ),
        lq.bar(
          range(2),
          (real-real.len(), fp-fp.len()),
          offset: group-w / 4,
          width: group-w / 2,
          fill: correct-fill,
          label: [PostCQL Correct],
        ),
        lq.place(group-w / 4, real-real.len() / 2, pct-label(real-correct-ratio, fill: white)),
        lq.place(1 + group-w / 4, fp-fp.len() / 2, pct-label(fp-correct-ratio, fill: white)),
      )
    },
  )
}
