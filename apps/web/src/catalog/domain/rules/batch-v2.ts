import { declareRule } from "./registry.ts";

// CatalogBatchV2 planning rules (S07). planBatch (../batch-plan.ts) reports every failure, never the first (G-5).

export const BATCH_DUPLICATE = declareRule("batch.duplicate", "An id or course slug appears once per collection of a batch.");
export const BATCH_REFERENCE = declareRule("batch.reference", "Every id a batch names exists in the batch or in the catalog.");
export const BATCH_REF_CONFLICT = declareRule("batch.ref-conflict", "A stored reference with different content is a conflict unless updateRefs is set.");
export const BATCH_INSTITUTION_KIND = declareRule("batch.institution-kind", "Rows and courses name an institution, never a lecturer (D-024).");
export const BATCH_HOME_ROW = declareRule("batch.home-row", "A course sits on its own institution's row; an institution has one row (INV-H5, D-016).");
export const BATCH_COVER = declareRule("batch.cover", "Every cover of a batch is a registered media object (uploaded before, by sha).");
export const BATCH_COVER_KIND = declareRule("batch.cover-kind", "A cover kind is one that owner type accepts (D-035). The plan rejects any other kind before apply.");
export const BATCH_COURSE = declareRule("batch.course", "A batch course is a consistent CourseBundle (editions, lessons, texts).");
export const COVER_DECLARED = declareRule("cover.declared", "A course's coverFrom is its own subarea, or its area when it has none, and that owner has every required cover kind (D-031).");
