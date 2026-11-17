/** Editorial lesson kinds. `lecture` is the ordinary lesson; the others are named parts of an edition. The database CHECK reads `lessonKinds`. */
export const lessonKind = {
  lecture: "lecture",
  background: "background",
  compilation: "compilation",
  trailer: "trailer",
} as const;

export const lessonKinds = [lessonKind.lecture, lessonKind.background, lessonKind.compilation, lessonKind.trailer] as const;
