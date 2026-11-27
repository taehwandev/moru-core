//! Owner: private bounded completion-policy JSON protocol.
//! Allowed: existing source guard, completion owners, receipt identity, std/JSON.
//! Forbidden: shells, providers, policy/state writes or public authority.
//! Callers/tests: thin completion adapter; native completion and bundle tests.
use crate::pending_publication_partition::PendingPublicationPartition;
use crate::pending_publication_status::PendingPublicationStatus;
use crate::publication_evidence::PublicationEvidence;
use crate::{
    completion_progress::Progress, completion_quality::Quality,
    completion_requirements::Requirements, legacy_publication_head::LegacyPublicationHead,
    local_delivery_identity::LocalDeliveryIdentity,
    local_delivery_observation::LocalDeliveryObservation,
    local_delivery_prepare::LocalDeliveryPrepare,
    pending_publication_receipt::PendingPublicationReceipt,
    pending_publication_transition::PendingPublicationTransition, pretool_guard::CallbackGuard,
    route_identity::RouteIdentity,
};
use serde_json::{json, Value};
use std::{
    ffi::OsString,
    io::{Read, Write},
    os::fd::AsFd,
};

#[path = "hq_decision_ingress.rs"]
pub(crate) mod hq_decision_ingress;
#[path = "hq_decision_cli.rs"]
mod hq_decision_cli;
#[path = "hq_report_replace.rs"]
mod hq_report_replace;
#[path = "hq_report_run_id.rs"]
mod hq_report_run_id;
#[path = "hq_report_assembly.rs"]
mod hq_report_assembly;
#[path = "hq_report_encoding.rs"]
mod hq_report_encoding;
#[path = "capsule_artifact.rs"]
mod capsule_artifact;
#[path = "capsule_binding.rs"]
mod capsule_binding;
#[path = "capsule_check_cli.rs"]
pub(crate) mod capsule_check_cli;
#[path = "capsule_cli_args.rs"]
mod capsule_cli_args;
#[path = "capsule_refresh_cli.rs"]
pub(crate) mod capsule_refresh_cli;
#[path = "capsule_directory.rs"]
mod capsule_directory;
#[path = "capsule_doc_drift.rs"]
mod capsule_doc_drift;
#[path = "capsule_ledger.rs"]
mod capsule_ledger;
#[path = "capsule_shape.rs"]
mod capsule_shape;
#[path = "capsule_worktree_signature.rs"]
mod capsule_worktree_signature;

pub(crate) struct CompletionProcess;

#[path = "doctor_launcher.rs"]
mod doctor_launcher;
#[path = "doctor_memory.rs"]
mod doctor_memory;
#[path = "doctor_node_manifests.rs"]
mod doctor_node_manifests;
#[path = "doctor_permission_count.rs"]
mod doctor_permission_count;
#[path = "doctor_project.rs"]
mod doctor_project;
#[path = "doctor_project_facts.rs"]
mod doctor_project_facts;
#[path = "doctor_report.rs"]
mod doctor_report;

#[path = "pending_publication_settlement.rs"]
pub(super) mod pending_publication_settlement;
#[path = "preflight_failures.rs"]
mod preflight_failures;
#[path = "structure_diff.rs"]
mod structure_diff;
#[path = "structure_block_findings.rs"]
mod structure_block_findings;
#[path = "structure_block_spans.rs"]
mod structure_block_spans;
#[path = "structure_python_blocks.rs"]
mod structure_python_blocks;
#[path = "structure_style_blocks.rs"]
mod structure_style_blocks;
#[path = "structure_code_blocks.rs"]
mod structure_code_blocks;
#[path = "structure_file_size.rs"]
mod structure_file_size;
#[path = "structure_source_layout.rs"]
mod structure_source_layout;
#[path = "structure_package_roles.rs"]
mod structure_package_roles;
#[path = "structure_owner_findings.rs"]
mod structure_owner_findings;
#[path = "structure_owner_facts.rs"]
mod structure_owner_facts;
#[path = "structure_removal_matching.rs"]
mod structure_removal_matching;
#[path = "structure_removal_inputs.rs"]
mod structure_removal_inputs;
#[path = "structure_removal_analysis.rs"]
mod structure_removal_analysis;
#[path = "structure_removal_redaction.rs"]
mod structure_removal_redaction;
#[path = "structure_move_matching.rs"]
mod structure_move_matching;
#[path = "structure_merge_baseline.rs"]
mod structure_merge_baseline;
#[path = "structure_report.rs"]
mod structure_report;
#[path = "structure_action_delta.rs"]
mod structure_action_delta;
#[path = "kotlin_literal_mask.rs"]
mod kotlin_literal_mask;
#[path = "kotlin_compose_bodies.rs"]
mod kotlin_compose_bodies;
#[path = "kotlin_compose_aliases.rs"]
mod kotlin_compose_aliases;
#[path = "kotlin_compose_callbacks.rs"]
mod kotlin_compose_callbacks;
#[path = "kotlin_compose_viewmodels.rs"]
mod kotlin_compose_viewmodels;
#[path = "kotlin_compose_source_findings.rs"]
mod kotlin_compose_source_findings;
#[path = "kotlin_compose_action_findings.rs"]
mod kotlin_compose_action_findings;
#[path = "structure_net_deletions.rs"]
mod structure_net_deletions;
#[path = "structure_source_paths.rs"]
mod structure_source_paths;
#[path = "structure_source_read.rs"]
mod structure_source_read;
#[path = "structure_go_declarations.rs"]
mod structure_go_declarations;
#[path = "structure_ts_text.rs"]
mod structure_ts_text;
#[path = "structure_js_declarations.rs"]
mod structure_js_declarations;
#[path = "structure_kotlin_declarations.rs"]
mod structure_kotlin_declarations;
#[path = "structure_brace_declarations.rs"]
mod structure_brace_declarations;
#[path = "structure_rust_declarations.rs"]
mod structure_rust_declarations;
#[path = "structure_declaration_roles.rs"]
mod structure_declaration_roles;
#[path = "structure_declaration_records.rs"]
mod structure_declaration_records;
#[path = "structure_review_baseline.rs"]
mod structure_review_baseline;
#[path = "structure_unstaged_match.rs"]
mod structure_unstaged_match;
#[path = "structure_diff_acquisition.rs"]
mod structure_diff_acquisition;
#[path = "live_web_check_lookup.rs"]
mod live_web_check_lookup;
#[path = "lesson_compaction_inbox.rs"]
mod lesson_compaction_inbox;
#[path = "lesson_compaction_apply.rs"]
mod lesson_compaction_apply;
#[path = "lesson_compaction_cli.rs"]
pub(crate) mod lesson_compaction_cli;
#[path = "lesson_compaction_merge.rs"]
mod lesson_compaction_merge;
#[path = "lesson_compaction_preview.rs"]
mod lesson_compaction_preview;
#[path = "live_web_edit_log.rs"]
mod live_web_edit_log;
#[path = "live_web_edit_hook.rs"]
mod live_web_edit_hook;
#[path = "project_relative_path.rs"]
mod project_relative_path;
#[path = "loop_budget.rs"]
mod loop_budget;
#[path = "loop_verdict.rs"]
mod loop_verdict;
#[path = "maintenance_projects.rs"]
mod maintenance_projects;
#[path = "maintenance_owner.rs"]
mod maintenance_owner;
#[path = "maintenance_retention.rs"]
mod maintenance_retention;
#[path = "scheduler_recovery.rs"]
mod scheduler_recovery;
#[path = "status_trends.rs"]
mod status_trends;
#[path = "status_trend_windows.rs"]
mod status_trend_windows;
#[path = "status_trend_sqlite.rs"]
mod status_trend_sqlite;
#[path = "status_trend_projects.rs"]
pub(crate) mod status_trend_projects;
#[path = "status_trend_pipeline.rs"]
pub(crate) mod status_trend_pipeline;
#[path = "status_trend_route.rs"]
mod status_trend_route;
#[path = "status_trend_binding.rs"]
mod status_trend_binding;
#[path = "status_trend_metadata.rs"]
mod status_trend_metadata;
#[path = "status_trend_stamp.rs"]
mod status_trend_stamp;
#[path = "status_trend_run_files.rs"]
mod status_trend_run_files;
#[path = "path_claim_scan.rs"]
mod path_claim_scan;
#[path = "path_claim_wait.rs"]
mod path_claim_wait;
#[path = "path_claim_release.rs"]
mod path_claim_release;
#[path = "path_claim_filename.rs"]
mod path_claim_filename;
#[path = "path_claim_write.rs"]
mod path_claim_write;

impl CompletionProcess {
    fn checkout_field(operation: &str, payload: &Value) -> Option<Value> {
        use moru_checkout_identity::CheckoutIdentity;

        let fields = payload.as_object()?;
        let root = fields.get("root")?.as_str()?;
        if fields.len() != 1 || !root.starts_with('/') || root.contains('\0') {
            return None;
        }
        match operation {
            "checkout-common-dir" => Some(json!({"value": CheckoutIdentity::common_dir(root).ok()?})),
            "checkout-current-branch" => Some(json!({"value": CheckoutIdentity::branch(root).ok()?})),
            _ => None,
        }
    }

    pub(crate) fn run(launcher: &OsString, args: &[OsString]) -> i32 {
        if args.len() != 2 || CallbackGuard::root(launcher, "completion-probe").is_none() {
            return 125;
        }
        let mut bytes = Vec::new();
        if std::io::stdin()
            .take(1024 * 1024 + 1)
            .read_to_end(&mut bytes)
            .is_err()
            || bytes.len() > 1024 * 1024
        {
            return 125;
        }
        if args[1] == "capsule-identities" {
            return Self::respond(RouteIdentity::probe(&bytes));
        }
        if args[1] == "loop-state-encode" {
            return Self::write_encoded(crate::loop_status::LoopStatus::encode_persisted(&bytes));
        }
        let Ok(payload) = serde_json::from_slice::<Value>(&bytes) else {
            return 125;
        };
        if args[1] == "hq-decision-cli" {
            return match hq_decision_cli::run(&payload) {
                Some(Ok(result)) => Self::respond(Some(result)),
                Some(Err(_)) => 1,
                None => 125,
            };
        }
        if args[1] == "hq-report-replace" {
            return match hq_report_replace::replace(&payload) {
                Some(Ok(receipt)) => Self::respond(Some(receipt)),
                Some(Err(_)) => 1,
                None => 125,
            };
        }
        if args[1] == "live-web-edit-hook" {
            return match live_web_edit_hook::LiveWebEditHook::record(&payload) {
                Some(Ok(receipt)) => Self::respond(Some(receipt)),
                Some(Err(_)) => 1,
                None => 125,
            };
        }
        if args[1] == "path-claim-expire" {
            return match path_claim_release::PathClaimRelease::expire(&payload) {
                Some(Ok(line)) => Self::respond(Some(json!({"line": line}))),
                Some(Err(_)) => 1,
                None => 125,
            };
        }
        if args[1] == "path-claim-expire-batch" {
            return match path_claim_release::PathClaimRelease::expire_batch(&payload) {
                Some(Ok(receipt)) => Self::respond(Some(receipt)),
                Some(Err(_)) => 1,
                None => 125,
            };
        }
        if args[1] == "path-claim-release" {
            return match path_claim_release::PathClaimRelease::release(&payload) {
                Some(Ok(())) => Self::respond(Some(json!({"handled": true}))),
                Some(Err(_)) => 1,
                None => 125,
            };
        }
        if args[1] == "lesson-compaction-apply" {
            return match lesson_compaction_apply::LessonCompactionApply::apply(&payload) {
                Some(Ok(written)) => Self::respond(Some(json!({"written": written}))),
                Some(Err(_)) => 1,
                None => 125,
            };
        }
        if args[1] == "lesson-compaction-write-batch" {
            return match lesson_compaction_apply::LessonCompactionApply::batch(&payload) {
                Some(Ok(receipt)) => Self::respond(Some(receipt)),
                Some(Err(_)) => 1,
                None => 125,
            };
        }
        if args[1] == "lesson-compaction-mark-stale" {
            return match lesson_compaction_apply::LessonCompactionApply::mark_stale(&payload) {
                Some(Ok(marked)) => Self::respond(Some(json!({"marked": marked}))),
                Some(Err(_)) => 1,
                None => 125,
            };
        }
        if args[1] == "path-claim-release-selected" {
            return match path_claim_release::PathClaimRelease::release_selected(&payload) {
                Some(Ok(receipt)) => Self::respond(Some(receipt)),
                Some(Err(_)) => 1,
                None => 125,
            };
        }
        if args[1] == "path-claim-write" {
            return match path_claim_write::PathClaimWrite::write(&payload) {
                Some(Ok(written)) => Self::respond(Some(json!({"written": written}))),
                Some(Err(_)) => 1,
                None => 125,
            };
        }
        if args[1] == "path-claim-write-batch" {
            return match path_claim_write::PathClaimWrite::batch(&payload) {
                Some(Ok(receipt)) => Self::respond(Some(receipt)),
                Some(Err(_)) => 1,
                None => 125,
            };
        }
        if args[1] == "live-web-edit-append" {
            return match live_web_edit_log::LiveWebEditLog::append(&payload) {
                Some(Ok(receipt)) => Self::respond(Some(receipt)),
                Some(Err(_)) => 1,
                None => 125,
            };
        }
        if args[1] == "live-web-edit-record" {
            return match live_web_edit_log::LiveWebEditLog::record(&payload) {
                Some(Ok(receipt)) => Self::respond(Some(receipt)),
                Some(Err(_)) => 1,
                None => 125,
            };
        }
        if args[1] == "pending-publication-encode" {
            return Self::write_encoded(PendingPublicationReceipt::encode(payload));
        }
        let result = match args[1].to_str() {
            Some(operation @ ("checkout-common-dir" | "checkout-current-branch")) => {
                Self::checkout_field(operation, &payload)
            }
            Some("hq-report-run-id") => hq_report_run_id::HqReportRunId::resolve(&payload),
            Some("hq-finish-assemble") => hq_report_assembly::assemble(&payload, false),
            Some("hq-decision-assemble") => hq_report_assembly::assemble(&payload, true),
            Some("hq-report-encode") => hq_report_encoding::encode(&payload),
            Some("loop-budget") => loop_budget::LoopBudget::decide(&payload),
            Some("loop-verdict") => loop_verdict::LoopVerdict::decide(&payload),
            Some("maintenance-projects") => maintenance_projects::MaintenanceProjects::scan(&payload),
            Some("maintenance-retention") => maintenance_retention::MaintenanceRetention::plan(&payload),
            Some("maintenance-settlement") => maintenance_retention::MaintenanceRetention::expired_runs(&payload),
            Some("maintenance-protected-runs") => maintenance_retention::MaintenanceRetention::protected_runs(&payload),
            Some("maintenance-recover-runs") => maintenance_retention::MaintenanceRetention::recover_runs(&payload),
            Some("scheduler-stale-tasks") => scheduler_recovery::SchedulerRecovery::stale(&payload),
            Some("scheduler-next-attempt") => scheduler_recovery::SchedulerRecovery::next_attempt(&payload),
            Some("status-trend-groups") => status_trends::StatusTrends::summarize(&payload),
            Some("status-trend-windows") => status_trend_windows::TrendWindows::bind(&payload),
            Some("status-trend-db" | "status-trend-db-utc") => status_trend_sqlite::TrendSqlite::read(&payload),
            Some("status-trend-report") => status_trends::StatusTrends::report(&payload),
            Some("status-trend-projects") => status_trend_projects::discover(&payload),
            Some("status-trend-metadata") => status_trend_run_files::read(&payload).and_then(|rows| status_trend_metadata::project(&rows)),
            Some("status-trend-binding") => status_trend_binding::TrendBinding::bind(&payload),
            Some("status-trend-run-files") => status_trend_run_files::read(&payload),
            Some("structure-diff") => structure_diff::StructureDiff::decode(&payload),
            Some("structure-diff-acquisition") => structure_diff_acquisition::StructureDiffAcquisition::probe(&payload),
            Some("structure-file-size") => structure_file_size::StructureFileSize::batch(&payload),
            Some("structure-removal-matching") => structure_removal_matching::StructureRemovalMatching::compare(&payload),
            Some("structure-removal-inputs") => structure_removal_inputs::StructureRemovalInputs::probe(&payload),
            Some("structure-removal-analysis") => structure_removal_analysis::StructureRemovalAnalysis::probe(&payload),
            Some("live-web-check") => live_web_check_lookup::LiveWebCheckLookup::probe(&payload),
            Some("lesson-compaction-inbox") => lesson_compaction_inbox::LessonCompactionInbox::probe(&payload),
            Some("lesson-compaction-merge") => lesson_compaction_merge::LessonCompactionMerge::probe(&payload),
            Some("lesson-compaction-preview") => lesson_compaction_preview::LessonCompactionPreview::probe(&payload),
            Some("lesson-compaction-apply-report") => lesson_compaction_preview::LessonCompactionPreview::apply_report(&payload),
            Some("live-web-check-history") => live_web_check_lookup::LiveWebCheckLookup::history(&payload),
            Some("path-claim-arguments") => project_relative_path::ProjectRelativePath::claim_arguments(&payload),
            Some("path-claim-scan") => path_claim_scan::PathClaimScan::probe(&payload),
            Some("path-claim-wait") => path_claim_wait::PathClaimWait::probe(&payload),
            Some("structure-move-matching") => structure_move_matching::StructureMoveMatching::compare(&payload),
            Some("structure-merge-baseline") => structure_merge_baseline::StructureMergeBaseline::classify(&payload),
            Some("structure-report") => structure_report::StructureReport::render(&payload),
            Some("structure-action-delta") => structure_action_delta::StructureActionDelta::classify(&payload),
            Some("kotlin-literal-mask") => kotlin_literal_mask::KotlinLiteralMask::mask(&payload),
            Some("structure-block-spans") => structure_block_spans::StructureBlockSpans::batch(&payload),
            Some("structure-python-classes") => structure_python_blocks::StructurePythonBlocks::top_level_classes(&payload),
            Some("structure-go-declarations") => structure_go_declarations::StructureGoDeclarations::scan(&payload),
            Some("structure-ts-text") => structure_ts_text::StructureTsText::process(&payload),
            Some("structure-js-declarations") => structure_js_declarations::StructureJsDeclarations::request(&payload),
            Some("structure-kotlin-declarations") => structure_kotlin_declarations::StructureKotlinDeclarations::scan(&payload),
            Some("structure-brace-declarations") => structure_brace_declarations::StructureBraceDeclarations::scan(&payload),
            Some("structure-rust-declarations") => structure_rust_declarations::StructureRustDeclarations::scan(&payload),
            Some("structure-declaration-roles") => structure_declaration_roles::StructureDeclarationRoles::classify(&payload),
            Some("structure-declaration-records") => structure_declaration_records::StructureDeclarationRecords::scan(&payload),
            Some("structure-review-baseline") => structure_review_baseline::StructureReviewBaseline::batch(&payload),
            Some("structure-unstaged-match") => structure_unstaged_match::StructureUnstagedMatch::probe(&payload),
            Some("structure-unstaged-plan") => structure_unstaged_match::StructureUnstagedMatch::plan(&payload),
            Some("structure-boundary-reasons") => structure_declaration_roles::StructureDeclarationRoles::boundary_reasons(&payload),
            Some("structure-source-paths") => structure_source_paths::StructureSourcePaths::filter(&payload),
            Some("structure-source-read") => structure_source_read::StructureSourceRead::batch(&payload),
            Some("preflight-failures") => preflight_failures::PreflightFailures::collect(&payload),
            Some("doctor-launcher") => doctor_launcher::DoctorLauncher::inspect(&payload),
            Some("doctor-memory") => doctor_memory::DoctorMemory::summarize(&payload),
            Some("doctor-node-manifests") => doctor_node_manifests::DoctorNodeManifests::inspect(&payload),
            Some("doctor-active-runs") => crate::status_process::StatusProcess::active_runs(&payload),
            Some("doctor-project") => doctor_project::DoctorProject::inspect(&payload),
            Some("doctor-project-facts") => doctor_project_facts::DoctorProjectFacts::collect(&payload),
            Some("doctor-permission-markers") => doctor_project::DoctorProject::permission_markers(&payload),
            Some("doctor-permission-count") => doctor_permission_count::DoctorPermissionCount::inspect(&payload),
            Some("doctor-report") => doctor_report::DoctorReport::build(&payload),
            Some("capsule-binding") => capsule_binding::CapsuleBinding::fingerprint(&payload),
            Some("capsule-replace") => capsule_artifact::CapsuleArtifact::replace(&payload),
            Some("capsule-refresh") => capsule_artifact::CapsuleArtifact::refresh(&payload),
            Some("capsule-read") => capsule_artifact::CapsuleArtifact::read(&payload),
            Some("capsule-doc-drift") => capsule_doc_drift::CapsuleDocDrift::compare(&payload),
            Some("capsule-directory") => capsule_directory::CapsuleDirectory::capture(&payload),
            Some("capsule-worktree-signature") => {
                capsule_worktree_signature::WorktreeSignature::capture(&payload)
            }
            Some("capsule-ledger") => capsule_ledger::CapsuleLedger::check(&payload),
            Some("capsule-shape") => capsule_shape::CapsuleShape::validate(&payload),
            Some("quality") => Quality::inspect(&payload),
            Some("requirements") => Requirements::validate(&payload),
            Some("coverage") => Requirements::coverage(&payload),
            Some("progress") => Progress::inspect(&payload),
            Some("staged-v1") => LocalDeliveryIdentity::capture(&payload),
            Some("staged-v1-observe") => LocalDeliveryObservation::probe(&payload),
            Some("legacy-publication-head") => LegacyPublicationHead::probe(&payload),
            Some("publication-upstream-config") => LegacyPublicationHead::upstream(&payload),
            Some("publication-pr-proof") => PublicationEvidence::pull_request(&payload),
            Some("publication-upstream-proof") => PublicationEvidence::upstream(&payload),
            Some("staged-v1-prepare") => LocalDeliveryPrepare::probe(&payload),
            Some("pending-publication-read") => PendingPublicationReceipt::probe(&payload),
            Some("pending-publication-replace") => PendingPublicationReceipt::replace(&payload),
            Some("pending-publication-status") => PendingPublicationStatus::probe(&payload),
            Some("pending-publication-partition") => PendingPublicationPartition::probe(&payload),
            Some("pending-publication-prepare") => PendingPublicationTransition::prepare(&payload),
            Some("pending-publication-observe") => PendingPublicationTransition::observe(&payload),
            Some("pending-publication-local-settlement") => {
                pending_publication_settlement::LocalSettlement::prepare(&payload)
            }
            _ => None,
        };
        Self::respond(result)
    }

    fn write_encoded(encoded: Option<String>) -> i32 {
        let Some(encoded) = encoded else {
            return 125;
        };
        // Stdout's console wrapper can suppress EBADF. Report descriptor
        // failures so the caller can reset its owned temporary.
        let Ok(descriptor) = std::io::stdout().as_fd().try_clone_to_owned() else {
            return 1;
        };
        let mut output = std::fs::File::from(descriptor);
        i32::from(
            output
                .write_all(encoded.as_bytes())
                .and_then(|_| output.flush())
                .is_err(),
        )
    }

    fn respond(result: Option<Value>) -> i32 {
        let Some(result) = result else {
            return 125;
        };
        let Ok(mut output) = serde_json::to_vec(&json!({"schema_version":1,"result":result}))
        else {
            return 1;
        };
        output.push(b'\n');
        if std::io::stdout().write_all(&output).is_ok() {
            0
        } else {
            1
        }
    }
}

fn capsule_json_integers(value: &Value) -> bool {
    match value {
        // serde_json can represent a large integer as a float.
        Value::Number(number) => number.is_i64() || number.is_u64(),
        Value::Array(items) => items.iter().all(capsule_json_integers),
        Value::Object(items) => items.values().all(capsule_json_integers),
        _ => true,
    }
}
