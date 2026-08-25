/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import React, { useState, useRef, useEffect, useMemo } from "react";
import { observer } from "mobx-react";
import { useParams } from "next/navigation";
import { FormProvider, useForm } from "react-hook-form";
// editor
import { ETabIndices, DEFAULT_WORK_ITEM_FORM_VALUES } from "@plane/constants";
import type { EditorRefApi } from "@plane/editor";
// i18n
import { useTranslation } from "@plane/i18n";
import { Button } from "@plane/propel/button";
import { TOAST_TYPE, setToast } from "@plane/propel/toast";
import type { TIssue, TWorkspaceDraftIssue } from "@plane/types";
// hooks
import { ToggleSwitch } from "@plane/ui";
import {
  convertWorkItemDataToSearchResponse,
  getUpdateFormDataForReset,
  cn,
  getTextContent,
  getChangedIssuefields,
  getTabIndex,
} from "@plane/utils";
// The1Studio fork (work-item creation defaults) — the create modal prefills an
// assignee and today's due date, and re-resolves the assignee when the project
// changes. DEFAULT_WORK_ITEM_FORM_VALUES lives in the sealed @plane/constants
// package and getUpdateFormDataForReset in the sealed @plane/utils, so the
// overrides are applied here instead of inside either.
import {
  getProjectChangeFormReset,
  getWorkItemCreationDefaults,
  resolveCreationAssigneeIds,
} from "@plane/work-item-defaults-ext";
// components
import {
  IssueDefaultProperties,
  IssueDescriptionEditor,
  IssueParentTag,
  IssueProjectSelect,
  IssueTitleInput,
} from "@/components/issues/issue-modal/components";
// helpers
// hooks
import { useIssueModal } from "@/hooks/context/use-issue-modal";
import { useIssueDetail } from "@/hooks/store/use-issue-detail";
import { useMember } from "@/hooks/store/use-member";
import { useUser } from "@/hooks/store/user";
import { useProject } from "@/hooks/store/use-project";
import { useProjectState } from "@/hooks/store/use-project-state";
import { useWorkspaceDraftIssues } from "@/hooks/store/workspace-draft";
import { usePlatformOS } from "@/hooks/use-platform-os";
import { useProjectIssueProperties } from "@/hooks/use-project-issue-properties";
// plane web imports
import { DeDupeButtonRoot } from "@/plane-web/components/de-dupe/de-dupe-button";
import { DuplicateModalRoot } from "@/plane-web/components/de-dupe/duplicate-modal";
import { IssueTypeSelect, WorkItemTemplateSelect } from "@/plane-web/components/issues/issue-modal";
import { WorkItemModalAdditionalProperties } from "@/plane-web/components/issues/issue-modal/modal-additional-properties";
import { useDebouncedDuplicateIssues } from "@/plane-web/hooks/use-debounced-duplicate-issues";

export interface IssueFormProps {
  data?: Partial<TIssue>;
  issueTitleRef: React.MutableRefObject<HTMLInputElement | null>;
  isCreateMoreToggleEnabled: boolean;
  onAssetUpload: (assetId: string) => void;
  onCreateMoreToggleChange: (value: boolean) => void;
  onChange?: (formData: Partial<TIssue> | null) => void;
  onClose: () => void;
  onSubmit: (values: Partial<TIssue>, is_draft_issue?: boolean) => Promise<void>;
  projectId: string;
  isDraft: boolean;
  moveToIssue?: boolean;
  modalTitle?: string;
  primaryButtonText?: {
    default: string;
    loading: string;
  };
  isDuplicateModalOpen: boolean;
  handleDuplicateIssueModal: (isOpen: boolean) => void;
  handleDraftAndClose?: () => void;
  isProjectSelectionDisabled?: boolean;
  showActionButtons?: boolean;
  dataResetProperties?: any[];
}

export const IssueFormRoot = observer(function IssueFormRoot(props: IssueFormProps) {
  const { t } = useTranslation();
  const {
    data,
    issueTitleRef,
    onAssetUpload,
    onChange,
    onClose,
    onSubmit,
    projectId: defaultProjectId,
    isCreateMoreToggleEnabled,
    onCreateMoreToggleChange,
    isDraft,
    moveToIssue = false,
    modalTitle = `${data?.id ? t("update") : isDraft ? t("create_a_draft") : t("create_new_issue")}`,
    primaryButtonText = {
      default: `${data?.id ? t("update") : isDraft ? t("save_to_drafts") : t("save")}`,
      loading: `${data?.id ? t("updating") : t("saving")}`,
    },
    isDuplicateModalOpen,
    handleDuplicateIssueModal,
    handleDraftAndClose,
    isProjectSelectionDisabled = false,
    showActionButtons = true,
    dataResetProperties = [],
  } = props;

  // states
  const [gptAssistantModal, setGptAssistantModal] = useState(false);
  const [isMoving, setIsMoving] = useState<boolean>(false);

  // refs
  const editorRef = useRef<EditorRefApi>(null);
  const submitBtnRef = useRef<HTMLButtonElement | null>(null);
  const formRef = useRef<HTMLFormElement | null>(null);
  const modalContainerRef = useRef<HTMLDivElement | null>(null);

  // router
  const { workspaceSlug, projectId: routeProjectId } = useParams();

  // store hooks
  const { getProjectById } = useProject();
  const {
    workItemTemplateId,
    isApplyingTemplate,
    selectedParentIssue,
    setWorkItemTemplateId,
    setSelectedParentIssue,
    getIssueTypeIdOnProjectChange,
    getActiveAdditionalPropertiesLength,
    handlePropertyValuesValidation,
    handleCreateUpdatePropertyValues,
    handleTemplateChange,
  } = useIssueModal();
  const { isMobile } = usePlatformOS();
  // The1Studio fork (work-item creation defaults)
  const { data: currentUser } = useUser();
  const {
    project: { getProjectMemberIds },
  } = useMember();
  const { moveIssue } = useWorkspaceDraftIssues();

  const {
    issue: { getIssueById },
  } = useIssueDetail();
  const { fetchCycles, fetchMembers } = useProjectIssueProperties();
  const { getStateById } = useProjectState();

  // The1Studio fork (work-item creation defaults) — everything the resolver in
  // @plane/work-item-defaults-ext needs to pick an assignee for ONE project.
  //
  // `getProjectMemberIds(id, false)` drops GUEST (role 5), matching the server's
  // `role >= 15` floor in plane/issue_defaults_ext/defaults.py. It returns null
  // for a project whose roster has never been fetched — pass that null through
  // untouched, because the resolver treats it as "unknown", not "nobody".
  const getAssigneeContext = (forProjectId: string | null | undefined, currentAssigneeIds?: string[] | null) => {
    const defaultAssignee = forProjectId ? getProjectById(forProjectId)?.default_assignee : null;
    return {
      currentAssigneeIds,
      currentUserId: currentUser?.id,
      // Typed `IUser | string | null` — a project fetched through different
      // endpoints gives back either shape, so never assume the id form.
      projectDefaultAssigneeId: typeof defaultAssignee === "string" ? defaultAssignee : (defaultAssignee?.id ?? null),
      assignableMemberIds: forProjectId ? getProjectMemberIds(forProjectId, false) : null,
    };
  };

  // form info
  const methods = useForm<TIssue>({
    // The1Studio fork (work-item creation defaults) — create mode only. An edit
    // must never re-fill a field the user has just cleared, and `data?.id` is how
    // this shared modal tells create from update. Spread AFTER the upstream
    // defaults and BEFORE `data`, so a template, a duplicated work item, or any
    // caller-supplied value still wins. Read once, on the first render, which is
    // why it resolves against the prop rather than the watched project id.
    defaultValues: {
      ...DEFAULT_WORK_ITEM_FORM_VALUES,
      ...(data?.id ? {} : getWorkItemCreationDefaults(getAssigneeContext(defaultProjectId))),
      project_id: defaultProjectId,
      ...data,
    },
    reValidateMode: "onChange",
  });
  const {
    formState,
    formState: { isDirty, isSubmitting, dirtyFields },
    handleSubmit,
    reset,
    watch,
    control,
    getValues,
    setValue,
  } = methods;

  const projectId = watch("project_id");

  // The1Studio fork (work-item creation defaults) — the roster is read here so
  // both the memo below and the correction effect share one subscription, and so
  // the effect can depend on the JOINED ids. getProjectMemberIds is a computedFn
  // returning a fresh array; depending on its identity re-runs the effect forever.
  const assignableMemberIds = projectId ? getProjectMemberIds(projectId, false) : null;
  const assignableMemberKey = assignableMemberIds?.join(",") ?? null;

  // Create mode only, and resolved against whichever project is selected NOW —
  // "Create more" clears the form for the next item, which must be prefilled for
  // the project still on screen, not the one the modal opened on.
  const creationDefaults = useMemo(
    () => (data?.id ? {} : getWorkItemCreationDefaults(getAssigneeContext(projectId))),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [data?.id, currentUser?.id, projectId, assignableMemberKey]
  );

  const activeAdditionalPropertiesLength = getActiveAdditionalPropertiesLength({
    projectId: projectId,
    workspaceSlug: workspaceSlug?.toString(),
    watch: watch,
  });

  // derived values
  const projectDetails = projectId ? getProjectById(projectId) : undefined;
  const isDisabled = isSubmitting || isApplyingTemplate;

  const { getIndex } = getTabIndex(ETabIndices.ISSUE_FORM, isMobile);

  //reset few fields on projectId change
  useEffect(() => {
    if (isDirty) {
      if (workItemTemplateId) {
        // reset work item template id
        setWorkItemTemplateId(null);
        // The1Studio fork (work-item creation defaults)
        reset({ ...DEFAULT_WORK_ITEM_FORM_VALUES, ...creationDefaults, project_id: projectId });
        editorRef.current?.clearEditor();
      } else {
        // The1Studio fork (work-item creation defaults) — getUpdateFormDataForReset
        // rebuilds the form from DEFAULT_WORK_ITEM_FORM_VALUES and carries forward
        // only name/description/priority/start_date/target_date, so assignee_ids
        // fell back to []. On create, re-resolve it for the NEW project instead of
        // emptying it. Edit mode keeps upstream's behaviour untouched.
        //
        // The branch above this one is dead on this fork — workItemTemplateId is
        // hardcoded null in apps/web/ce/components/issues/issue-modal/provider.tsx
        // — so this `else` is the only path a project change actually takes.
        reset(
          data?.id
            ? getUpdateFormDataForReset(projectId, getValues())
            : getProjectChangeFormReset(projectId, getValues(), getAssigneeContext(projectId))
        );
      }
    }
    if (projectId && routeProjectId !== projectId) {
      fetchCycles(workspaceSlug?.toString(), projectId);
      // The1Studio fork (work-item creation defaults) — nothing else here fetches
      // the new project's roster, and the correction effect below waits on it.
      fetchMembers(workspaceSlug?.toString(), projectId);
    }

    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId]);

  // The1Studio fork (work-item creation defaults) — the roster for a newly chosen
  // project usually arrives AFTER the switch, so the assignee resolved above was
  // resolved optimistically, without knowing who is assignable. Re-check it once
  // the list lands.
  useEffect(() => {
    if (data?.id || !projectId || assignableMemberIds === null) return;

    const current = (getValues("assignee_ids") ?? []) as string[];
    const resolved = resolveCreationAssigneeIds(getAssigneeContext(projectId, current));
    if (resolved.length === current.length && resolved.every((id, index) => id === current[index])) return;

    // shouldDirty:false — a correction the user did not make must not arm the
    // unsaved-changes prompt on close.
    setValue("assignee_ids", resolved, { shouldDirty: false });

    // Deps change only on a project switch, a roster arrival, or the user store
    // hydrating — a pick the user makes afterwards cannot be undone by this,
    // because the member dropdown fetches the roster itself before it can be
    // opened. currentUser is in here for the cold-start case: without it, a modal
    // opened before the user store resolves settles on an empty assignee and
    // never re-resolves once the id arrives.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId, assignableMemberKey, currentUser?.id]);

  // Reset form when data prop changes
  useEffect(() => {
    if (data) {
      // The1Studio fork (work-item creation defaults)
      reset({ ...DEFAULT_WORK_ITEM_FORM_VALUES, ...creationDefaults, project_id: projectId, ...data });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...dataResetProperties]);

  // Update the issue type id when the project id changes
  useEffect(() => {
    const issueTypeId = watch("type_id");

    // if issue type id is present or project not available, return
    if (issueTypeId || !projectId) return;

    // get issue type id on project change
    const issueTypeIdOnProjectChange = getIssueTypeIdOnProjectChange(projectId);
    if (issueTypeIdOnProjectChange) setValue("type_id", issueTypeIdOnProjectChange, { shouldValidate: true });

    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data, projectId]);

  useEffect(() => {
    if (workItemTemplateId && editorRef.current) {
      handleTemplateChange({
        workspaceSlug: workspaceSlug?.toString(),
        reset,
        editorRef,
      });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [workItemTemplateId]);

  const handleFormSubmit = async (formData: Partial<TIssue>, is_draft_issue = false) => {
    // Check if the editor is ready to discard
    if (!editorRef.current?.isEditorReadyToDiscard()) {
      setToast({
        type: TOAST_TYPE.ERROR,
        title: t("error"),
        message: t("editor_is_not_ready_to_discard_changes"),
      });
      return;
    }

    // check for required properties validation
    if (
      !handlePropertyValuesValidation({
        projectId: projectId,
        workspaceSlug: workspaceSlug?.toString(),
        watch: watch,
      })
    )
      return;

    const submitData = !data?.id
      ? formData
      : {
          ...getChangedIssuefields(formData, dirtyFields as { [key: string]: boolean | undefined }),
          project_id: getValues<"project_id">("project_id"),
          id: data.id,
          description_html: formData.description_html ?? "<p></p>",
          type_id: getValues<"type_id">("type_id"),
        };

    // this condition helps to move the issues from draft to project issues
    if (formData.hasOwnProperty("is_draft")) submitData.is_draft = formData.is_draft;

    try {
      await onSubmit(submitData, is_draft_issue);
      setGptAssistantModal(false);
      if (isCreateMoreToggleEnabled && workItemTemplateId) {
        handleTemplateChange({
          workspaceSlug: workspaceSlug?.toString(),
          reset,
          editorRef,
        });
      } else {
        reset({
          ...DEFAULT_WORK_ITEM_FORM_VALUES,
          // The1Studio fork (work-item creation defaults) — "Create more"
          // clears the form for the NEXT new work item, so it prefills too;
          // otherwise the second item comes out bare while the first did not.
          // creationDefaults is resolved against the project still SELECTED,
          // which is why it is keyed on the watched id rather than the prop.
          ...creationDefaults,
          ...(isCreateMoreToggleEnabled ? { ...data } : {}),
          project_id: getValues<"project_id">("project_id"),
          type_id: getValues<"type_id">("type_id"),
          description_html: data?.description_html ?? "<p></p>",
        });
        editorRef?.current?.clearEditor();
      }
    } catch (error) {
      console.error(error);
    }
  };

  const handleMoveToProjects = async () => {
    if (!data?.id || !data?.project_id || !data) return;
    setIsMoving(true);
    try {
      await handleCreateUpdatePropertyValues({
        issueId: data.id,
        issueTypeId: data.type_id,
        projectId: data.project_id,
        workspaceSlug: workspaceSlug?.toString(),
        isDraft: true,
      });

      await moveIssue(workspaceSlug.toString(), data.id, {
        ...data,
        ...getValues(),
      } as TWorkspaceDraftIssue);
    } catch {
      setToast({
        type: TOAST_TYPE.ERROR,
        title: "Error!",
        message: "Failed to move work item to project. Please try again.",
      });
    } finally {
      setIsMoving(false);
    }
  };

  const condition =
    (watch("name") && watch("name") !== "") || (watch("description_html") && watch("description_html") !== "<p></p>");

  const handleFormChange = () => {
    if (!onChange) return;

    if (isDirty && condition) onChange(watch());
    else onChange(null);
  };

  // debounced duplicate issues swr
  const { duplicateIssues } = useDebouncedDuplicateIssues(
    workspaceSlug?.toString(),
    projectDetails?.workspace.toString(),
    projectId ?? undefined,
    {
      name: watch("name"),
      description_html: getTextContent(watch("description_html")),
      issueId: data?.id,
    }
  );

  // executing this useEffect when the parent_id coming from the component prop
  useEffect(() => {
    const parentId = watch("parent_id") || undefined;
    if (!parentId) return;
    if (parentId === selectedParentIssue?.id || selectedParentIssue) return;

    const issue = getIssueById(parentId);
    if (!issue) return;

    const parentProjectDetails = getProjectById(issue.project_id);
    if (!parentProjectDetails) return;

    const stateDetails = getStateById(issue.state_id);

    setSelectedParentIssue(
      convertWorkItemDataToSearchResponse(workspaceSlug?.toString(), issue, parentProjectDetails, stateDetails)
    );
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [watch, getIssueById, getProjectById, selectedParentIssue, getStateById]);

  // executing this useEffect when isDirty changes
  useEffect(() => {
    if (!onChange) return;

    if (isDirty && condition) onChange(watch());
    else onChange(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isDirty]);

  useEffect(() => {
    const formElement = formRef?.current;
    const modalElement = modalContainerRef?.current;

    if (!formElement || !modalElement) return;

    const resizeObserver = new ResizeObserver(() => {
      modalElement.style.maxHeight = `${formElement?.offsetHeight}px`;
    });

    resizeObserver.observe(formElement);

    return () => {
      resizeObserver.disconnect();
    };
  }, [formRef, modalContainerRef]);

  // TODO: Remove this after the de-dupe feature is implemented

  const shouldRenderDuplicateModal = isDuplicateModalOpen && duplicateIssues?.length > 0;

  return (
    <FormProvider {...methods}>
      <div className="flex gap-2 bg-transparent">
        <div className="w-full rounded-lg">
          <form
            ref={formRef}
            onSubmit={handleSubmit((formData) => handleFormSubmit(formData))}
            className="flex w-full flex-col"
          >
            <div className="rounded-t-lg bg-surface-1 p-5">
              <h3 className="pb-2 text-h4-medium text-secondary">{modalTitle}</h3>
              <div className="flex items-center justify-between pt-2 pb-4">
                <div className="flex items-center gap-x-1">
                  <IssueProjectSelect
                    control={control}
                    disabled={!!data?.id || !!data?.sourceIssueId || isProjectSelectionDisabled}
                    handleFormChange={handleFormChange}
                  />
                  {projectId && (
                    <IssueTypeSelect
                      control={control}
                      projectId={projectId}
                      editorRef={editorRef}
                      disabled={!!data?.sourceIssueId}
                      handleFormChange={handleFormChange}
                      renderChevron
                    />
                  )}
                  {projectId && !data?.id && !data?.sourceIssueId && (
                    <WorkItemTemplateSelect
                      projectId={projectId}
                      typeId={watch("type_id")}
                      handleModalClose={() => {
                        if (handleDraftAndClose) {
                          handleDraftAndClose();
                        } else {
                          onClose();
                        }
                      }}
                      handleFormChange={handleFormChange}
                      renderChevron
                    />
                  )}
                </div>
                {duplicateIssues.length > 0 && (
                  <DeDupeButtonRoot
                    workspaceSlug={workspaceSlug?.toString()}
                    isDuplicateModalOpen={isDuplicateModalOpen}
                    label={
                      duplicateIssues.length === 1
                        ? `${duplicateIssues.length} ${t("duplicate_issue_found")}`
                        : `${duplicateIssues.length} ${t("duplicate_issues_found")}`
                    }
                    handleOnClick={() => handleDuplicateIssueModal(!isDuplicateModalOpen)}
                  />
                )}
              </div>
              {watch("parent_id") && selectedParentIssue && (
                <div className="pb-4">
                  <IssueParentTag
                    control={control}
                    selectedParentIssue={selectedParentIssue}
                    handleFormChange={handleFormChange}
                    setSelectedParentIssue={setSelectedParentIssue}
                  />
                </div>
              )}
              <div className="space-y-1">
                <IssueTitleInput
                  control={control}
                  issueTitleRef={issueTitleRef}
                  formState={formState}
                  handleFormChange={handleFormChange}
                />
              </div>
            </div>
            <div
              className={cn(
                "space-y-3 bg-surface-1 pb-4",
                activeAdditionalPropertiesLength > 4 &&
                  "vertical-scrollbar scrollbar-sm max-h-[45vh] overflow-hidden overflow-y-auto"
              )}
            >
              <div className="px-5">
                <IssueDescriptionEditor
                  control={control}
                  isDraft={isDraft}
                  issueName={watch("name")}
                  issueId={data?.id}
                  descriptionHtmlData={data?.description_html}
                  editorRef={editorRef}
                  submitBtnRef={submitBtnRef}
                  gptAssistantModal={gptAssistantModal}
                  workspaceSlug={workspaceSlug?.toString()}
                  projectId={projectId}
                  handleFormChange={handleFormChange}
                  handleDescriptionHTMLDataChange={(description_html) =>
                    setValue<"description_html">("description_html", description_html)
                  }
                  setGptAssistantModal={setGptAssistantModal}
                  handleGptAssistantClose={() => reset(getValues())}
                  onAssetUpload={onAssetUpload}
                  onClose={onClose}
                />
              </div>
              <WorkItemModalAdditionalProperties
                isDraft={isDraft}
                workItemId={data?.id ?? data?.sourceIssueId}
                projectId={projectId}
                workspaceSlug={workspaceSlug?.toString()}
              />
            </div>
            <div
              className={cn(
                "rounded-b-lg border-t-[0.5px] border-subtle bg-surface-1 px-4 py-3",
                activeAdditionalPropertiesLength > 0 && "shadow-raised-100"
              )}
            >
              <div className="pb-3">
                <IssueDefaultProperties
                  control={control}
                  id={data?.id}
                  projectId={projectId}
                  workspaceSlug={workspaceSlug?.toString()}
                  selectedParentIssue={selectedParentIssue}
                  startDate={watch("start_date")}
                  targetDate={watch("target_date")}
                  parentId={watch("parent_id")}
                  isDraft={isDraft}
                  handleFormChange={handleFormChange}
                  setSelectedParentIssue={setSelectedParentIssue}
                />
              </div>
              {showActionButtons && (
                <div
                  className="flex items-center justify-end gap-4 border-t-[0.5px] border-subtle pt-6 pb-3"
                  tabIndex={getIndex("create_more")}
                >
                  {!data?.id && (
                    <button
                      type="button"
                      className="inline-flex cursor-pointer items-center gap-1.5"
                      onClick={() => onCreateMoreToggleChange(!isCreateMoreToggleEnabled)}
                    >
                      <ToggleSwitch value={isCreateMoreToggleEnabled} onChange={() => {}} size="sm" />
                      <span className="text-caption-sm-regular">{t("create_more")}</span>
                    </button>
                  )}
                  <div className="flex items-center gap-2">
                    <div tabIndex={getIndex("discard_button")}>
                      <Button
                        variant="secondary"
                        size="lg"
                        onClick={() => {
                          if (editorRef.current?.isEditorReadyToDiscard()) {
                            onClose();
                          } else {
                            setToast({
                              type: TOAST_TYPE.ERROR,
                              title: "Error!",
                              message: "Editor is still processing changes. Please wait before proceeding.",
                            });
                          }
                        }}
                      >
                        {t("discard")}
                      </Button>
                    </div>
                    <div tabIndex={isDraft ? getIndex("submit_button") : getIndex("draft_button")}>
                      <Button
                        variant={moveToIssue ? "secondary" : "primary"}
                        size="lg"
                        type="submit"
                        ref={submitBtnRef}
                        loading={isSubmitting}
                        disabled={isDisabled}
                      >
                        {isSubmitting ? primaryButtonText.loading : primaryButtonText.default}
                      </Button>
                    </div>

                    {moveToIssue && (
                      <Button
                        variant="primary"
                        type="button"
                        loading={isMoving}
                        onClick={handleMoveToProjects}
                        disabled={isMoving}
                        size="lg"
                      >
                        {t("add_to_project")}
                      </Button>
                    )}
                  </div>
                </div>
              )}
            </div>
          </form>
        </div>
        {shouldRenderDuplicateModal && (
          <div
            ref={modalContainerRef}
            className="shadow-xl bg-pi-50 relative flex flex-col gap-2.5 rounded-lg px-3 py-4"
            style={{ maxHeight: formRef?.current?.offsetHeight ? `${formRef.current.offsetHeight}px` : "436px" }}
          >
            <DuplicateModalRoot
              workspaceSlug={workspaceSlug.toString()}
              issues={duplicateIssues}
              handleDuplicateIssueModal={handleDuplicateIssueModal}
            />
          </div>
        )}
      </div>
    </FormProvider>
  );
});
