import { getCourseMedia } from "@tower/media";
import { pickAsset } from "@/media/domain/group";
import { MediaImage } from "@/media/client/MediaImage";

export default async function MediaFixturePage() {
  return <MediaImage asset={pickAsset((await getCourseMedia(["course-1"])).get("course-1"), "poster_9x16")} sizes="208px" />;
}
