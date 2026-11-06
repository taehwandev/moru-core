//! owner: FigmaReport; allowed imports: shared PythonJson/std; forbidden imports:
//! I/O/schema/coverage recomputation; callers/tests: Figma validator;
//! verification: exact canonical Markdown report and final newline.
use crate::python_json::{PythonJson, Value};
pub(crate) struct FigmaReport;
impl FigmaReport {
    /// Render the complete coverage object produced by FigmaCoverage.
    pub(crate) fn render(coverage: &Value, problems: &[String]) -> Option<String> {
        let mut lines = vec![
            "# Figma Handoff Validation Report".to_owned(),
            String::new(),
        ];
        if problems.is_empty() {
            lines.push("## ✅ No Schema Violations".into());
        } else {
            lines.push(format!("## ❌ Schema Violations ({})", problems.len()));
            lines.extend(problems.iter().map(|p| format!("- {p}")));
        }
        let assets = &coverage["assets"];
        let layout = &coverage["layoutNodes"];
        let warnings = &coverage["warnings"];
        let components = &coverage["components"];
        let icons = &coverage["iconInventory"];
        let variables = &coverage["variables"];
        let image_total = Self::count(&assets["imageFillTotal"])?;
        let asset_total = Self::count(&assets["total"])?;
        let image_percent = if image_total == 0 {
            100
        } else {
            Self::count(&assets["imageFillWithPath"])?.checked_mul(100)? / image_total
        };
        let asset_percent = if asset_total == 0 {
            0
        } else {
            Self::count(&assets["withPath"])?.checked_mul(100)? / asset_total
        };
        let text = PythonJson::string;
        lines.extend([
            String::new(), "## Fidelity Coverage".into(),
            format!("- Screens: {}", text(&coverage["screens"])),
            format!("- Components: {} (instances {} / variants {} / blueprints {})", text(&components["total"]), text(&components["instances"]), text(&components["withVariant"]), text(&components["blueprints"])),
            format!("- layoutNodes: {} (opacity {} / stroke {} / rotation {} / renderBounds {})", text(&layout["total"]), text(&layout["withOpacity"]), text(&layout["withStrokeWeight"]), text(&layout["withRotation"]), text(&layout["withRenderBounds"])),
            format!("- Colors {} / gradients {} / text styles {} / text runs {} / effects {}", text(&coverage["colors"]), text(&coverage["gradients"]), text(&coverage["textStyles"]), text(&coverage["textRuns"]), text(&coverage["effects"])),
            format!("- Image-fill recovery: {}/{} ({image_percent}%)", text(&assets["imageFillWithPath"]), text(&assets["imageFillTotal"])),
            format!("- Overall asset recovery: {}/{} ({asset_percent}%), fallback chains {}", text(&assets["withPath"]), text(&assets["total"]), text(&assets["withFallbackChain"])),
            format!("- Unique icons: {} (name unclear {} / named by component {}), assets linked to components {}", text(&icons["unique"]), text(&icons["nameUnclear"]), text(&icons["namedByComponent"]), text(&assets["withNearestComponent"])),
            format!("- Variables: {} (metadata {})", text(&variables["count"]), if PythonJson::truthy(&variables["metadataAvailable"]) { "available" } else { "unavailable" }),
            format!("- Warnings: {} (asset not renderable {} / variables {} / other {})", text(&warnings["total"]), text(&warnings["assetNotRenderable"]), text(&warnings["variables"]), text(&warnings["other"])),
        ]);
        Some(lines.join("\n") + "\n")
    }
    fn count(value: &Value) -> Option<u128> {
        match value {
            Value::Number(n) => n.text().parse().ok(),
            _ => None,
        }
    }
}
