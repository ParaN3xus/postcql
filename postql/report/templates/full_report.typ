#import "template.typ": common-styles, single-report
#import "@preview/numbly:0.1.0": numbly
#import "@preview/lilaq:0.6.0" as lq

#let reports = json(bytes(sys.inputs.at("reports_json", default: read("full-example.json"))))

#let verdict-order = ("real", "false_positive", "uncertain")
#let verdict-labels = ("Real", "False Positive", "Uncertain")
#let codeql-severity-order = ("recommendation", "warning", "error")
#let codeql-severity-labels = ("Recommendation", "Warning", "Error")
#let severity-order = ("low", "medium", "high", "critical")
#let triage-severity-labels = ("Low", "Medium", "High", "Critical")

#let count-by(items, field, value) = {
  items.filter(item => item.at(field) == value).len()
}

#let verdict-counts = verdict-order.map(verdict => count-by(reports, "verdict", verdict))

#let severity-alignment-matrix = codeql-severity-order.map(codeql-severity => {
  severity-order.map(triage-severity => {
    reports.filter(item => item.raw_row.severity == codeql-severity and item.severity == triage-severity).len()
  })
})

#let row-sum(values) = values.fold(0, (acc, value) => acc + value)

#let normalize-row(values) = {
  let total = row-sum(values)
  if total == 0 {
    values.map(_ => 0.0)
  } else {
    values.map(value => value * 1.0 / total)
  }
}

#let severity-alignment-ratios = severity-alignment-matrix.map(normalize-row)

#let total-alerts = reports.len()
#let real-count = count-by(reports, "verdict", "real")
#let false-positive-count = count-by(reports, "verdict", "false_positive")
#let uncertain-count = count-by(reports, "verdict", "uncertain")

#let pct(value, total) = {
  if total == 0 {
    "0.0%"
  } else {
    str(calc.round(value * 1000.0 / total) / 10.0) + "%"
  }
}


#set document(title: "CodeQL Alert Triage Report")
#show: common-styles

#title()

= Summary <summary>

Triage completed for #strong[#total-alerts] CodeQL alerts.
The current batch contains #strong[#real-count alerts triaged as real (#pct(real-count, total-alerts))], #strong[#false-positive-count alerts triaged as false positive (#pct(false-positive-count, total-alerts))], and #strong[#uncertain-count alerts triaged as uncertain (#pct(uncertain-count, total-alerts))].

== Verdict Distribution

#figure(lq.diagram(
  height: 8em,
  xaxis: (
    ticks: verdict-labels.enumerate(),
    subticks: none,
  ),

  lq.bar(
    (0, 1, 2),
    verdict-counts,
    width: 68%,
    fill: teal,
    stroke: none,
  ),
  lq.hlines(total-alerts, total-alerts, stroke: blue, label: [Total]),
))

== CodeQL Severity x Triage Severity

#let severity-mesh = lq.colormesh(
  (0, 1, 2, 3),
  (0, 1, 2),
  severity-alignment-ratios,
  map: gradient.linear(..color.map.cividis.rev()),
)
#figure({
  lq.diagram(
    height: 8em,
    xaxis: (
      ticks: triage-severity-labels.enumerate(),
      label: [Triage Severity],
      subticks: none,
    ),
    yaxis: (
      ticks: codeql-severity-labels.enumerate(),
      label: [CodeQL Severity],
      subticks: none,
    ),
    severity-mesh,
  )
  [ ]
  lq.colorbar(
    severity-mesh,
    orientation: "vertical",
    thickness: 2.6mm,
    height: 8em,
  )
})

== Contents
#context outline(target: selector(heading).after(here()), depth: 1, title: none)


#set page(header: {
  set text(blue)
  underline(link(<summary>)[Go back to summary])
})
#pagebreak(weak: true)


#set heading(numbering: numbly(
  x => str(x - 1) + ".",
  (x, y) => str(x - 1) + "." + str(y - 1) + ".",
))

#(
  reports // .slice(20)
    .map(entry => {
      heading("Report #" + str(entry.raw_row.row_index))
      single-report(entry, heading-offset: 1)
      pagebreak(weak: true)
    })
    .join()
)
