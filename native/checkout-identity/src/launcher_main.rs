use std::env;
use std::ffi::OsString;
use std::io::{self, Write};
use std::os::unix::process::CommandExt;
use std::process::{exit, Command};

use moru_checkout_identity::CheckoutIdentity;

mod agy_hook_process;
mod agy_skill_read;
mod android_manifest;
mod argparse_help;
mod atomic_sibling;
mod behavior_trace;
mod behavior_eval;
mod behavior_eval_artifact;
mod behavior_eval_cli;
mod behavior_eval_input;
mod behavior_eval_process;
mod behavior_review;
mod behavior_trace_process;
mod callback_replay;
mod callback_state;
mod cards_bootstrap;
mod cards_identity;
mod cards_process;
mod cards_recall;
mod cards_resume;
mod cards_resume_child;
mod cards_resume_exec;
mod cards_resume_input;
mod cards_resume_output;
mod cards_resume_process;
mod cards_resume_signal;
mod cards_resume_signal_mask;
mod cards_resume_terminal;
mod cards_schema;
mod cards_store;
mod cards_transaction;
mod cards_write_process;
mod completion_process;
mod smoke_hook_suite;
#[cfg(unix)]
mod smoke_workspace;
mod mutation_check;
mod mutation_check_command;
mod route_identity;
mod completion_progress;
mod completion_quality;
mod completion_requirements;
mod codex_statusline;
mod discovery_candidates;
mod discovery_fs;
mod discovery_groups;
mod discovery_paths;
mod discovery_process;
mod discovery_registry;
mod discovery_search;
mod doc_transcript;
mod doc_transcript_process;
mod wikimap_search;
#[path = "dispatch_guardian/mod.rs"]
mod dispatch_guardian;
mod figma_coverage;
mod figma_process;
mod figma_validation;
mod figma_validation_report;
#[allow(dead_code)] // Shared source; this crate only uses the status adapter.
mod gitrun;
mod launcher_backend;
mod literal_args;
mod legacy_publication_head;
mod local_delivery_identity;
mod local_delivery_observation;
mod local_delivery_prepare;
mod local_delivery_search;
mod mailbox_process;
mod mailbox_state;
mod mailbox_status_process;
mod mailbox_status_state;
mod memory_terms;
mod memory_recall;
mod memory_context;
mod memory_process;
mod memory_json;
mod memory_record;
mod memory_files;
mod memory_source;
mod memory_status;
mod memory_history;
mod memory_analysis;
mod memory_consolidation;
mod memory_upkeep;
mod memory_review;
mod manifest_process;
mod next_process;
mod next_verification;
mod overhead_aggregate;
mod overhead_cli;
mod overhead_clock;
mod overhead_collection;
mod overhead_command;
mod overhead_format;
mod overhead_hooks;
mod overhead_process;
mod overhead_report;
mod overhead_report_text;
mod overhead_session;
mod overhead_stamp;
mod overhead_stats;
mod loop_status;
#[cfg(target_os = "macos")]
#[path = "next_owner_darwin.rs"]
mod darwin_process;
mod runtime_identity;
mod overhead_text;
mod overhead_timings;
mod pending_publication_partition;
mod pending_publication_cli;
mod pending_publication_receipt;
mod pending_publication_status;
mod pending_publication_transition;
mod pretool_files;
mod pretool_guard;
mod pretool_process;
mod pretool_query;
mod pretool_scope;
mod pretool_transcript;
mod publication_evidence;
mod python_encoding;
mod python_float;
mod python_input_file;
mod python_json;
mod python_mean;
mod python_sum;
mod python_text;
mod react_manifest;
mod read_process;
mod registry_read;
mod status_process;
mod status_trend_cli;
mod status_snapshot;
mod status_state;
mod statusline;
mod statusline_chain;
mod statusline_process;
mod stop_process;
mod stop_state;
#[allow(dead_code)] // Git text decoding shares the library's text contract.
mod text;
mod worker_completion;
mod worker_completion_process;
mod workflow_query_process;
mod workflow_index_descriptions;
mod decision_cache_plan;
mod decision_cached_result;
mod decision_cli;
mod decision_input;
mod decision_report;
mod review_packet_assembly;
mod review_packet_output;
mod review_packet_snapshot;
mod decision_response;
mod workflow_offline_score;
mod workflow_wikimap_rank;
mod unittest_admission;
use launcher_backend::Backend;

const USAGE: &str = "usage: moru-native-launcher PYTHON_LAUNCHER [ARGS...]\n       moru-native-launcher PYTHON_LAUNCHER checkout-identity [--help]\n";
const CHECKOUT_USAGE: &str = "usage: moru-hook checkout-identity < requests.ndjson\n";

// Native handler exits are softened only under the existing hook convention.
fn finish(code: i32) -> ! {
    let soft = env::var_os("MORU_HOOK_SOFT_FAIL").map_or(false, |v| v == "1");
    exit(if code != 0 && soft { 0 } else { code })
}

// Replace the process with the legacy Python launcher; never returns.
fn exec_python(launcher: &OsString, args: &[OsString]) -> ! {
    let err = Command::new("python3").arg(launcher).args(args).exec();
    eprintln!("moru-native-launcher: failed to exec python3: {err}");
    exit(127)
}

fn native_checkout_identity(extra: &[OsString]) -> i32 {
    match extra {
        [] => {
            let stdin = io::stdin();
            let stdout = io::stdout();
            match CheckoutIdentity::serve(stdin.lock(), stdout.lock()) {
                Ok(()) => 0,
                Err(err) => {
                    eprintln!("moru-native-launcher: checkout-identity I/O error: {err}");
                    1
                }
            }
        }
        [flag] if flag == "--help" => {
            let mut out = io::stdout().lock();
            match out
                .write_all(CHECKOUT_USAGE.as_bytes())
                .and_then(|_| out.flush())
            {
                Ok(()) => 0,
                Err(err) => {
                    eprintln!("moru-native-launcher: failed to write usage: {err}");
                    1
                }
            }
        }
        _ => {
            eprintln!("moru-native-launcher: checkout-identity accepts no arguments except --help");
            2
        }
    }
}

fn direct_dispatch(launcher: &OsString, args: &[OsString]) -> Option<i32> {
    Some(match args.first().and_then(|arg| arg.to_str())? {
        "--setup-probe" => codex_statusline::CodexStatusLine::run(launcher, args),
        "loop" => finish(loop_status::LoopStatus::run(launcher, &args[1..])?),
        "codex-statusline-setup" => {
            finish(codex_statusline::CodexStatusLine::setup(launcher, &args[1..])?)
        }
        "--memory-probe" => memory_process::MemoryProcess::run(launcher, args),
        "--doc-transcript-probe" => doc_transcript_process::DocTranscriptProcess::run(launcher, args),
        "--wikimap-search-probe" => wikimap_search::WikimapSearch::run(launcher, args),
        "--cards-write-probe" => cards_write_process::CardWriteProcess::run(launcher, args),
        "--cards-probe" => cards_process::CardsProcess::probe(launcher, args),
        "--overhead-probe" => overhead_process::OverheadProcess::run(launcher, args),
        "--registry-read-probe" => registry_read::RegistryRead::run(launcher, args),
        "--completion-probe" => completion_process::CompletionProcess::run(launcher, args),
        "--smoke-hook-suite" => smoke_hook_suite::SmokeHookSuite::run(launcher, &args[1..]),
        "--workflow-query-probe" => workflow_query_process::WorkflowQueryProcess::run(launcher, args),
        "--decision-cache-probe" => decision_cache_plan::DecisionCachePlan::run(launcher, args),
        "--review-packet-probe" => review_packet_assembly::ReviewPacketAssembly::run(launcher, args),
        "agent-hq-report" => finish(completion_process::hq_decision_ingress::run(launcher, args)),
        "microsoft-decision" => finish(decision_cache_plan::DecisionCachePlan::alias(launcher, &args[1..])?),
        "smoke-checks" => finish(smoke_hook_suite::SmokeHookSuite::alias(launcher, args)),
        _ => return None,
    })
}

fn dispatch_callback(launcher: &OsString, args: &[OsString]) {
    let code = match args.first().and_then(|arg| arg.to_str()) {
        Some("claude-stop-gate" | "codex-stop-gate") => stop_process::StopProcess::run(launcher, args),
        Some("mailbox-hook") => mailbox_process::MailboxProcess::run(launcher, args),
        Some("agy-hook") => agy_hook_process::AgyHookProcess::run(launcher, args),
        Some("claude-pretool-gate" | "codex-pretool-gate") => {
            pretool_process::PretoolProcess::run(launcher, args)
        }
        _ => return,
    };
    finish(code)
}

fn main() {
    let mut argv = env::args_os().skip(1);
    let launcher = match argv.next() {
        Some(l) => l,
        None => {
            eprint!("moru-native-launcher: missing PYTHON_LAUNCHER\n{USAGE}");
            exit(2);
        }
    };
    let args: Vec<OsString> = argv.collect();
    if args.first().is_some_and(|arg| arg == "--mutation-check") {
        exit(mutation_check::MutationCheck::run(&launcher, &args[1..]));
    }
    if args.first().is_some_and(|arg| arg == "--behavior-eval") {
        exit(behavior_eval_cli::BehaviorEvalCli::run(&args[1..]));
    }
    if args.first().is_some_and(|arg| arg == "--behavior-review-export") {
        exit(behavior_review::BehaviorReview::run(&args));
    }
    if args.first().is_some_and(|arg| arg == "--dispatch-guardian" || arg == "--dispatch-exec-gate") {
        exit(dispatch_guardian::DispatchGuardian::run(&launcher, &args));
    }
    if args.first().is_some_and(|arg| arg == "--unittest-admission") {
        // This private, source-verified path must never soften or replay failures.
        exit(unittest_admission::UnittestAdmission::run(&args[1..]));
    }
    behavior_trace_process::BehaviorTraceProcess::dispatch(&args);
    worker_completion_process::WorkerCompletionProcess::dispatch(&args);

    if let Some(code) = direct_dispatch(&launcher, &args) {
        exit(code);
    }

    if args.first().is_some_and(|arg| arg == "runs-prune") {
        exit(registry_read::RegistryRead::runs_prune(&launcher, &args));
    }
    if args.first().is_some_and(|arg| arg == "lessons-compact") {
        exit(completion_process::lesson_compaction_cli::LessonCompactionCli::run(&launcher, &args));
    }

    if args.first().is_some_and(|a| a == "agent-mailbox") {
        finish(mailbox_status_process::MailboxStatusProcess::run(
            &launcher, &args,
        ));
    }

    if args.first().is_some_and(|a| a == "work-cards") {
        finish(cards_process::CardsProcess::run(&launcher, &args));
    }

    if args.first().is_some_and(|a| a == "figma-validate") {
        finish(figma_process::FigmaProcess::run(&launcher, &args));
    }
    if args.first().is_some_and(|a| a == "behavior-eval") {
        finish(behavior_eval_process::BehaviorEvalProcess::run(&launcher, &args));
    }
    mutation_check_command::MutationCheckCommand::dispatch(&launcher, &args);
    if args.first().is_some_and(|a| a == "experience-eval") {
        finish(memory_process::experience_cli::ExperienceCli::run(&launcher, &args));
    }
    if args.first().is_some_and(|a| a == "pending-publication") {
        exit(pending_publication_cli::PendingPublicationCli::run(&launcher, &args));
    }
    if args.first().is_some_and(|a| a == "execution-capsule") {
        if let Some(code) = completion_process::capsule_check_cli::CapsuleCheck::run(&launcher, &args) {
            finish(code);
        }
        if let Some(code) = completion_process::capsule_refresh_cli::CapsuleRefresh::run(&launcher, &args) {
            finish(code);
        }
    }
    if args.first().is_some_and(|a| a == "overhead-report") {
        finish(overhead_command::OverheadCommand::run(&launcher, &args));
    }

    if args.first().is_some_and(|a| {
        a == "check-android-skill-manifest" || a == "check-react-rn-skill-manifest"
    }) {
        finish(manifest_process::ManifestProcess::run(&launcher, &args));
    }

    if args.first().is_some_and(|a| a == "project-discover") {
        let code = discovery_process::DiscoveryProcess::run(&launcher, &args);
        if args.get(1).is_some_and(|a| a == "--native-probe") {
            exit(code);
        }
        finish(code);
    }

    if args.first().is_some_and(|a| a == "agent-os-status") {
        finish(status_process::StatusProcess::run(&launcher, &args));
    }

    if args.first().is_some_and(|a| a == "next") {
        finish(next_process::NextProcess::run(&launcher, &args));
    }

    dispatch_callback(&launcher, &args);

    if args
        .first()
        .map_or(false, |a| a == "claude-statusline" || a == "agy-statusline")
    {
        finish(statusline_process::StatuslineProcess::run(&launcher, &args));
    }

    if args.first().map_or(false, |a| a == "checkout-identity") {
        match Backend::from_env() {
            Backend::Python => exec_python(&launcher, &args),
            Backend::Unknown => {
                eprintln!("moru-native-launcher: unknown MORU_CHECKOUT_IDENTITY_BACKEND");
                finish(2);
            }
            Backend::Native => finish(native_checkout_identity(&args[1..])),
        }
    }

    exec_python(&launcher, &args)
}
