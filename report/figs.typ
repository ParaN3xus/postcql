#import "data.typ": alerts, fp-correct-ratio, fp-fp, gt-fp, gt-real, pv, real-correct-ratio, real-real
#import "@preview/cetz:0.4.2": canvas
#import "@preview/cetz-plot:0.1.3": chart
#import "@preview/lilaq:0.6.0" as lq
#import "colors.typ": *
#import "arch.typ": overall-struc

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
