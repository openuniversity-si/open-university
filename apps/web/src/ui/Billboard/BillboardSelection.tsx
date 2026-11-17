"use client";

import type { ReactNode } from "react";
import { useAuthSelection } from "@/identity/client/AuthProvider";
import type { BillboardView } from "@/catalog/domain/view-model";
import { CourseCard } from "@/ui/CourseCard/CourseCard";
import { HomeIntro } from "@/ui/HomeIntro/HomeIntro";
import { Rail } from "@/ui/Rail/Rail";
import { isEagerPoster } from "@/ui/Rail/eager";
import type { HomeShelf } from "@/ui/showcase/home-shelves";
import { Billboard } from "./Billboard";
import styles from "./BillboardSelection.module.css";

interface BillboardSelectionProps {
  readonly featured: BillboardView;
  readonly shelves: readonly HomeShelf[];
  /** Rendered after the rails (Home: the Portais section, server-rendered). */
  readonly children?: ReactNode;
  readonly intro: { readonly text: string; readonly link: string; readonly href: string };
}

/** Selection is explicit state, never derived from the initially featured course or pointer hover. */
export function BillboardSelection({ featured, shelves, intro, children }: BillboardSelectionProps) {
  const [selectedId, setSelectedId] = useAuthSelection("home");
  const course = shelves.flatMap((shelf) => shelf.courses).find((entry) => entry.id === selectedId) ?? featured;
  return (
    <>
      <Billboard course={course} selected={selectedId !== undefined} />
      <div className={styles.rails} data-testid="tower-home-rails">
        <HomeIntro text={intro.text} link={intro.link} href={intro.href} />
        {shelves.map((shelf, index) => (
          <Rail key={shelf.id} id={shelf.id} title={shelf.title}>{shelf.courses.map((entry, card) => {
            const resume = shelf.resume ? entry.progress?.card : undefined;
            if (shelf.resume && !resume) return null;
            return <CourseCard key={entry.id} course={entry} selected={entry.id === selectedId} onSelect={setSelectedId} {...(resume ? { resume } : {})} eager={isEagerPoster(index, card)} />;
          })}</Rail>
        ))}
        {children}
      </div>
    </>
  );
}
