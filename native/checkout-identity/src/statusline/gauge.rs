pub(crate) struct Gauge;

impl Gauge {
    const WIDTH: usize = 8;
    const PARTIAL: [char; 8] = [' ', '▏', '▎', '▍', '▌', '▋', '▊', '▉'];

    pub(crate) fn render(remaining: u32) -> String {
        let eighths = (f64::from(remaining) / 100.0 * 8.0 * 8.0).round_ties_even() as usize;
        let full = (eighths / 8).min(Self::WIDTH);
        let rem = eighths % 8;
        let mut out = "█".repeat(full);
        let mut used = full;
        if rem > 0 && full < Self::WIDTH {
            out.push(Self::PARTIAL[rem]);
            used += 1;
        }
        out.push_str(&"░".repeat(Self::WIDTH - used));
        out
    }
}
