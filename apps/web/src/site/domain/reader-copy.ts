/**
 * Reader chrome (D-050). Each key names what a reader sees and is the only spelling of that phrase.
 * A count noun is not a phrase key: the same letters also name an entity kind.
 */

/** Fills `{name}` holes. A missing hole stays visible so a wrong template cannot drop a word. */
export function fill(template: string, values: Readonly<Record<string, string>>): string {
  return template.replace(/\{([A-Za-z]+)\}/g, (match, key: string) => (key in values ? values[key] ?? match : match));
}

/** Title of a Home row that has no title and is not an author's row. */
export const continueWatchingTitle = "Continue Watching";

/** Nav label and page title of the universities section. */
export const universitiesTitle = "Universities";

/** Nav label and page title of the authors section. */
export const authorsTitle = "Authors";

/** Narrow middle dot between two reader-facing parts. */
export const metaDot = " · ";

/** Wide middle dot between meta parts: two spaces, a dot, two spaces. */
export const metaGap = "  ·  ";

/** Billboard status after the viewer selects that course. */
export const billboardSelected = "Selected";

/** Billboard status of the featured course before any selection. */
export const billboardFeatured = "Featured";

/** Kicker after a university's place name. */
export const universityKicker = "UNIVERSITY";

/** Credits row for a university cover. */
export const universityCoverKind = "University cover" as const;

/** Credits row for an author cover. */
export const authorCoverKind = "Author cover" as const;

/** The one sentence above the image credits. */
export const creditsNote = "Every cover is modified for Open University: cropped, toned warm black-and-white, with a gradient and title added.";

/** Link preview of /universities. */
export const universitiesDescription = "Complete university courses from MIT, Yale, Harvard, Stanford, Carnegie Mellon and Cornell, free and in order.";

/** Link preview of /authors. */
export const authorsDescription = "Lecture series by individual scholars, complete, free and in order.";

/** Closing of a universities count, including the comma. */
export const freeInOrderSuffix = ", free and in order.";

/** Label of a background lesson. */
export const lessonBackgroundLabel = "Background";

/** Label of a trailer. */
export const lessonTrailerLabel = "Trailer";

/** Label of a lab lesson. */
export const lessonLabLabel = "Lab";

/** Lesson kicker: its label, its index, and how many lessons the edition has. */
export const lessonPositionTemplate = "{label} {order} of {total}";

/** Course page title: the display title, then the author. */
export const courseByAuthorTemplate = "{title} by {author}";

/** Area page link preview: the university, the course count, and the area title. */
export const areaDescriptionTemplate = "{fullName}: {count} in {area}.";

/** Plural ending used when the noun just gains an s. */
export const nounPluralTemplate = "{noun}s";

/** Portal subtitle overflow: two spaces and a plus before the hidden count. */
export const morePrefix = "  +";

/** One course in a public count. The plural adds s. */
export const courseNoun = "course";

/** One subject area in a public count. The plural adds s. */
export const areaNoun = "area";

/** One institution on the universities page. */
export const institutionNoun = "institution";

/** Plural of `institutionNoun`. */
export const institutionNounMany = "institutions";

/** One university in a country line. */
export const universityNoun = "university";

/** Plural of `universityNoun`. */
export const universityNounMany = "universities";

/** One author on the authors portal. */
export const authorNoun = "author";

/** Plural of `authorNoun`. */
export const authorNounMany = "authors";

/** Labs half of an edition count. The approved line says "1 labs", so this is always plural. */
export const labsNoun = "labs";

/** Suffix after the rounded hour count on a course meta line. */
export const hourMark = "h";

/** Between the lecture count and the labs count on an edition. */
export const editionJoin = " + ";

/** Comma between names in a portal's accessible name. */
export const nameListSeparator = ", ";

/** Home tab label. */
export const homeTitle = "Home";

/** Account action that starts sign-in. */
export const signInLabel = "Sign in";

/** Accessible name of the brand mark. */
export const brandHomeLabel = "Open University, Home";

/** Accessible name of the primary navigation. */
export const primaryNavLabel = "Primary";

/** Accessible name of the account button. `{name}` is the viewer's name. */
export const accountForTemplate = "Account for {name}";

/** Account menu title. */
export const accountMenuLabel = "Account";

/** Account action that ends the session. */
export const signOutLabel = "Sign out";

/** Accessible name of the control that closes the account menu. */
export const closeAccountMenuLabel = "Close account menu";

/** Sign-in failed. The apostrophe is the typographic one the screen already uses. */
export const signInError = "Couldn’t sign in.";

/** The viewer closed the Google prompt. */
export const signInCancelled = "Sign-in cancelled.";

/** Button that repeats a failed sign-in or a failed lecture. */
export const tryAgainLabel = "Try again";

/** Busy line while Google sign-in is in flight. The ellipsis is the single character the screen already uses. */
export const continuingWithGoogle = "Continuing with Google…";

/** Empty catalog heading. */
export const emptyCatalogTitle = "No courses yet";

/** Empty catalog body. */
export const emptyCatalogBody = "New lectures will appear here.";

/** Render-error heading. */
export const errorTitle = "Something went wrong";

/** Not-found kicker. */
export const notFoundKicker = "404";

/** Not-found heading. */
export const notFoundTitle = "Page not found";

/** Not-found body. */
export const notFoundBody = "This page does not exist, or it has moved. The courses are right where you left them.";

/** Skip link. */
export const skipToContent = "Skip to content";

/** Footer label for the legal links. */
export const legalLabel = "Legal";

/** Play control on a lecture poster. */
export const playLecture = "Play lecture";

/** Status while a lecture is loading. */
export const loadingLecture = "Loading lecture";

/** The lecture file cannot play. */
export const lectureUnavailable = "This lecture can’t play right now.";

/** Accessible name of the lecture list. */
export const lectureNavigation = "Lecture navigation";

/** Previous lecture. */
export const previousLecture = "Previous";

/** Next lecture. */
export const nextLecture = "Next";

/** Word after Next on a wide screen, including the leading space. */
export const lectureWord = " lecture";

/** Link back to the course from a lecture. */
export const backToCourse = "Back to course";

/** Course progress heading. */
export const courseProgressLabel = "Course progress";

/** Watched count in the player rail. */
export const watchedCountTemplate = "{count} of {total} watched";

/** About heading on the course page. */
export const aboutThisCourse = "About this course";

/** About heading on the lecture page. */
export const aboutThisLecture = "About this lecture";

/** Course fact label. */
export const levelLabel = "Level";

/** Course fact label. */
export const lengthLabel = "Length";

/** Course fact label. */
export const languageLabel = "Language";

/** Course fact label. */
export const formatLabel = "Format";

/** Edition fact label. */
export const editionLabel = "Edition";

/** Course details heading. */
export const courseDetailsLabel = "Course details";

/** CTA when the viewer has not started the course. */
export const startLabel = "Start";

/** CTA when the viewer has started the course. */
export const resumeLabel = "Resume";

/** Selected course card. */
export const courseSelectedDescription = "Selected. Activate again to open the course.";

/** Link from a course card into the lecture list. */
export const viewLectures = "View lectures";

/** Control that marks a lecture complete. */
export const markComplete = "Mark complete";

/** Control after a lecture is complete. */
export const completedLabel = "Completed";

/** Playlist row that is the one on screen. */
export const nowPlaying = "Now playing";

/** Spoken form of the playing row, including the trailing space. */
export const nowPlayingDescribed = "Now playing. ";

/** Spoken form of a watched row, including the trailing space. */
export const watchedDescribed = "Watched. ";

/** Selected playlist row. */
export const lessonSelectedDescription = "Selected. Activate again to open the lesson.";

/** Unselected playlist row. */
export const lessonActivateDescription = "Activate to select the lesson.";

/** Universities page action. */
export const browseCourses = "Browse courses";

/** Universities page jump heading. */
export const jumpToArea = "Jump to an area";

/** Label before the area jump links. */
export const jumpToLabel = "Jump to:";

/** Overflow link on a university card. `{count}` is the hidden count. */
export const seeAllTemplate = "See all {count}";

/** Accessible name that opens a named card. `{name}` is the card name. */
export const openNameTemplate = "Open {name}";

/** University area action. */
export const exploreLabel = "Explore";

/** Fallback group when a university has no country. */
export const otherLabel = "Other";

/** Cover image that failed to load. */
export const coverUnavailable = "Cover unavailable";

/** Media that is still loading. */
export const mediaLoading = "Loading";

/** Resume line that names the lesson, with the wide dot already in the template. */
export const resumeLessonTemplate = "Resume{gap}{lesson}";

/** Resume line that names the time left, with the narrow dot already in the template. */
export const resumeMetaTemplate = "Resume{dot}{remaining}";

/** Heading of the other courses by the same author. `{name}` is the author. */
export const moreFromTemplate = "More from {name}";

/** Part header for the labs half of an edition. `{dot}` is the narrow separator. */
export const labsPartTemplate = "Labs{dot}{count}";

/** Hours phrase in an edition about line. */
export const hoursCountTemplate = "{hours} hours";

/** Edition about line: hours, then the lesson count. */
export const aboutLengthTemplate = "{hours}{dot}{count}";

/** Marker after the edition that is the current one. */
export const latestEditionSuffix = "{dot}latest";

/** Phrases a second spelling of which fails the UI-text gate. Count nouns are not here. */
export const readerPhrases = [
  continueWatchingTitle,
  universitiesTitle,
  authorsTitle,
  metaDot,
  metaGap,
  billboardSelected,
  billboardFeatured,
  universityKicker,
  universityCoverKind,
  authorCoverKind,
  creditsNote,
  universitiesDescription,
  authorsDescription,
  freeInOrderSuffix,
  lessonBackgroundLabel,
  lessonTrailerLabel,
  lessonLabLabel,
  lessonPositionTemplate,
  courseByAuthorTemplate,
  areaDescriptionTemplate,
  nounPluralTemplate,
  morePrefix,
  homeTitle,
  signInLabel,
  brandHomeLabel,
  primaryNavLabel,
  accountForTemplate,
  accountMenuLabel,
  signOutLabel,
  closeAccountMenuLabel,
  signInError,
  signInCancelled,
  tryAgainLabel,
  continuingWithGoogle,
  emptyCatalogTitle,
  emptyCatalogBody,
  errorTitle,
  notFoundKicker,
  notFoundTitle,
  notFoundBody,
  skipToContent,
  legalLabel,
  playLecture,
  loadingLecture,
  lectureUnavailable,
  lectureNavigation,
  previousLecture,
  nextLecture,
  lectureWord,
  backToCourse,
  courseProgressLabel,
  watchedCountTemplate,
  aboutThisCourse,
  aboutThisLecture,
  levelLabel,
  lengthLabel,
  languageLabel,
  formatLabel,
  editionLabel,
  courseDetailsLabel,
  startLabel,
  resumeLabel,
  courseSelectedDescription,
  viewLectures,
  markComplete,
  completedLabel,
  nowPlaying,
  nowPlayingDescribed,
  watchedDescribed,
  lessonSelectedDescription,
  lessonActivateDescription,
  moreFromTemplate,
  labsPartTemplate,
  browseCourses,
  jumpToArea,
  jumpToLabel,
  seeAllTemplate,
  openNameTemplate,
  exploreLabel,
  otherLabel,
  coverUnavailable,
  mediaLoading,
  hoursCountTemplate,
] as const;
