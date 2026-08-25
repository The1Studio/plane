/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import type { FC } from "react";
import { useEffect, useState } from "react";
import { observer } from "mobx-react";
import { useParams } from "next/navigation";
import type { UseFormRegister } from "react-hook-form";
import { useForm } from "react-hook-form";
// plane imports
import { useTranslation } from "@plane/i18n";
import { PlusIcon } from "@plane/propel/icons";
import { setPromiseToast } from "@plane/propel/toast";
import type { IProject, TIssue, EIssueLayoutTypes } from "@plane/types";
import { cn, createIssuePayload } from "@plane/utils";
// The1Studio fork (work-item creation defaults) — inline add gets the same
// prefill as the Add-work-item modal. createIssuePayload hardcodes
// `assignee_ids: []` in the sealed @plane/utils package, and the backend reads
// an explicit [] as a deliberate "nobody", so the value has to be supplied here.
import { getWorkItemCreationDefaults } from "@plane/work-item-defaults-ext";
// plane web imports
// hooks
import { useMember } from "@/hooks/store/use-member";
import { useProject } from "@/hooks/store/use-project";
import { useUser } from "@/hooks/store/user";
import { QuickAddIssueFormRoot } from "@/plane-web/components/issues/quick-add";
// local imports
import { CreateIssueToastActionItems } from "../../create-issue-toast-action-items";

export type TQuickAddIssueForm = {
  ref: React.RefObject<HTMLFormElement>;
  isOpen: boolean;
  projectDetail: IProject;
  hasError: boolean;
  register: UseFormRegister<TIssue>;
  onSubmit: () => void;
  isEpic: boolean;
};

export type TQuickAddIssueButton = {
  isEpic?: boolean;
  onClick: () => void;
};

type TQuickAddIssueRoot = {
  isQuickAddOpen?: boolean;
  layout: EIssueLayoutTypes;
  prePopulatedData?: Partial<TIssue>;
  QuickAddButton?: FC<TQuickAddIssueButton>;
  customQuickAddButton?: React.ReactNode;
  containerClassName?: string;
  setIsQuickAddOpen?: (isOpen: boolean) => void;
  quickAddCallback?: (projectId: string | null | undefined, data: TIssue) => Promise<TIssue | undefined>;
  isEpic?: boolean;
};

const defaultValues: Partial<TIssue> = {
  name: "",
};

export const QuickAddIssueRoot = observer(function QuickAddIssueRoot(props: TQuickAddIssueRoot) {
  const {
    isQuickAddOpen,
    layout,
    prePopulatedData,
    QuickAddButton,
    customQuickAddButton,
    containerClassName = "",
    setIsQuickAddOpen,
    quickAddCallback,
    isEpic = false,
  } = props;
  // i18n
  const { t } = useTranslation();
  // router
  const { workspaceSlug, projectId } = useParams();
  // The1Studio fork (work-item creation defaults)
  const { data: currentUser } = useUser();
  const { getProjectById } = useProject();
  const {
    project: { getProjectMemberIds },
  } = useMember();
  // states
  const [isOpen, setIsOpen] = useState(isQuickAddOpen ?? false);
  // form info
  const {
    reset,
    handleSubmit,
    setFocus,
    register,
    formState: { errors, isSubmitting },
  } = useForm<TIssue>({ defaultValues });

  useEffect(() => {
    if (isQuickAddOpen !== undefined) {
      setIsOpen(isQuickAddOpen);
    }
  }, [isQuickAddOpen]);

  useEffect(() => {
    if (!isOpen) reset({ ...defaultValues });
  }, [isOpen, reset]);

  // `nextIsOpen`, not `isOpen`: the outer state variable of that name is in
  // scope here and oxlint --deny-warnings flags the shadow across the whole
  // file, not just the diff. Pre-existing; unrelated to the creation defaults.
  const handleIsOpen = (nextIsOpen: boolean) => {
    if (isQuickAddOpen !== undefined && setIsQuickAddOpen) {
      setIsQuickAddOpen(nextIsOpen);
    } else {
      setIsOpen(nextIsOpen);
    }
  };

  const onSubmitHandler = async (formData: TIssue) => {
    if (isSubmitting || !workspaceSlug || !projectId) return;

    reset({ ...defaultValues });

    // The1Studio fork (work-item creation defaults) — resolved against the route
    // project: a workspace-level layout can reach one the viewer is not an
    // assignable member of, and prefilling them there produces a create the core
    // serializer rejects. The project wrapper has already fetched this project's
    // roster (apps/web/core/layouts/auth-layout/project-wrapper.tsx), so the
    // resolver is not guessing by the time a payload can be submitted.
    const defaultAssignee = getProjectById(projectId.toString())?.default_assignee;
    const creationDefaults = getWorkItemCreationDefaults({
      currentUserId: currentUser?.id,
      projectDefaultAssigneeId: typeof defaultAssignee === "string" ? defaultAssignee : (defaultAssignee?.id ?? null),
      assignableMemberIds: getProjectMemberIds(projectId.toString(), false),
    });

    const payload = createIssuePayload(projectId.toString(), {
      // FIRST on purpose. A later spread wins, and the group's own values must
      // beat this: the calendar prepopulates target_date from the day the user
      // clicked, and an assignee-grouped kanban column prepopulates
      // assignee_ids. Putting the defaults after prePopulatedData would silently
      // move every calendar-added item to today.
      ...creationDefaults,
      ...prePopulatedData,
      ...formData,
    });

    if (quickAddCallback) {
      const quickAddPromise = quickAddCallback(projectId.toString(), { ...payload });
      setPromiseToast<any>(quickAddPromise, {
        loading: isEpic ? t("epic.adding") : t("issue.adding"),
        success: {
          title: t("common.success"),
          message: () => `${isEpic ? t("epic.create.success") : t("issue.create.success")}`,
          actionItems: (data) => (
            // TODO: Translate here
            <CreateIssueToastActionItems
              workspaceSlug={workspaceSlug.toString()}
              projectId={projectId.toString()}
              issueId={data.id}
              isEpic={isEpic}
            />
          ),
        },
        error: {
          title: t("common.error.label"),
          message: (err) => err?.message || t("common.error.message"),
        },
      });

      await quickAddPromise;
    }
  };

  if (!projectId) return null;

  return (
    <div
      className={cn(
        containerClassName,
        errors && errors?.name && errors?.name?.message ? `border-danger-strong bg-danger-subtle` : ``
      )}
    >
      {isOpen ? (
        <QuickAddIssueFormRoot
          isOpen={isOpen}
          layout={layout}
          prePopulatedData={prePopulatedData}
          projectId={projectId?.toString()}
          hasError={!!errors?.name?.message}
          setFocus={setFocus}
          register={register}
          onSubmit={handleSubmit(onSubmitHandler)}
          onClose={() => handleIsOpen(false)}
          isEpic={isEpic}
        />
      ) : (
        <>
          {QuickAddButton && <QuickAddButton isEpic={isEpic} onClick={() => handleIsOpen(true)} />}
          {customQuickAddButton && <>{customQuickAddButton}</>}
          {!QuickAddButton && !customQuickAddButton && (
            <button
              className="flex w-full cursor-pointer items-center gap-2 bg-layer-transparent px-2 py-3 hover:bg-layer-transparent-hover"
              onClick={() => handleIsOpen(true)}
            >
              <PlusIcon className="h-3.5 w-3.5 stroke-2" />
              <span className="text-13 font-medium">{t(`${isEpic ? "epic.new" : "issue.new"}`)}</span>
            </button>
          )}
        </>
      )}
    </div>
  );
});
