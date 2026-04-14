#let n-alerts = 228

#let result-dir = "/work/results/analyze-all/"

#let gt = csv("../work/results/gt.csv").slice(1).map(x => x.last())

#let alerts = for i in range(n-alerts) {
  let row-dir = result-dir + str(i) + "/"
  let init-row-dir = "/work/results/analyze-all-initial/" + str(i) + "/"
  let eval-res = json(init-row-dir + "eval.json")
  let report-res = json(row-dir + "report.json")
  (
    (
      row-index: report-res.raw_row.row_index,
      gt-verdict: gt.at(report-res.raw_row.row_index),
      rule-name: report-res.raw_row.rule_name,
      rule-precision: report-res.raw_row.rule_precision,
      rule-security-severity: report-res.raw_row.rule_security_severity,
      alert-severity: report-res.raw_row.severity,
      verdict: report-res.verdict,
      severity: report-res.severity,
      fixed: eval-res.upstream_fixed,
    ),
  )
}

#let round1(x) = {
  let y = calc.round(x * 10) / 10
  if y == calc.round(y) {
    str(y) + ".0"
  } else {
    str(y)
  }
}

#let pv(x) = round1(100.0 * x) + "%"

#let count-alerts(pred) = alerts.filter(pred).len()
#let count-gt(label) = gt.filter(x => x == label).len()

#let gt-real = gt.enumerate().filter(x => x.last() == "real").map(x => x.first())
#let gt-fp = gt.enumerate().filter(x => x.last() == "false_positive").map(x => x.first())
#let agent-real = alerts.filter(x => x.verdict == "real" or x.verdict == "uncertain").map(x => x.row-index)
#let agent-fp = alerts.filter(x => x.verdict == "false_positive").map(x => x.row-index)

#let inter(a, b) = {
  a.filter(x => x in b)
}

#let real-real = inter(gt-real, agent-real)
#let fp-fp = inter(gt-fp, agent-fp)
#let real-fp = inter(gt-real, agent-fp)
#let fp-real = inter(gt-fp, agent-real)

#let agent-correct = real-real + fp-fp
#let real-correct-ratio = real-real.len() / gt-real.len()
#let real-wrong-ratio = real-fp.len() / gt-real.len()
#let fp-correct-ratio = fp-fp.len() / gt-fp.len()
#let fp-wrong-ratio = fp-real.len() / gt-fp.len()


#let agent-accuracy = agent-correct.len() / n-alerts
#let codeql-baseline-precision = gt-real.len() / n-alerts
#let codeql-baseline-accuracy = gt-real.len() / n-alerts
#let codeql-baseline-recall = 1.0
#let codeql-baseline-f1 = (
  2
    * codeql-baseline-precision
    * codeql-baseline-recall
    / (
      codeql-baseline-precision + codeql-baseline-recall
    )
)

#let agent-precision = real-real.len() / agent-real.len()
#let agent-recall = real-real.len() / gt-real.len()
#let agent-f1 = 2 * agent-precision * agent-recall / (agent-precision + agent-recall)

#let rule-count(name) = count-alerts(a => a.at("rule-name") == name)
#let rule-correct(name) = count-alerts(a => a.at("rule-name") == name and a.at("verdict") == a.at("gt-verdict"))
#let rule-accuracy(name) = 1.0 * rule-correct(name) / rule-count(name)

#let severity-count(value) = count-alerts(a => a.at("rule-security-severity") == value)
#let severity-correct(value) = count-alerts(a => (
  a.at("rule-security-severity") == value and a.at("verdict") == a.at("gt-verdict")
))
#let severity-accuracy(value) = 1.0 * severity-correct(value) / severity-count(value)
