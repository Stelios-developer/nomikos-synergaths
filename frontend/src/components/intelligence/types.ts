import type { DocumentIntelligenceStage } from '../../api/client'

export type CaseWorkspaceView = 'overview' | 'facts' | 'timeline' | 'risks' | 'actions' | 'decisions' | 'evidence'
export interface IntelligenceWorkflowState {
  phase: 'opening' | 'analysing' | 'brief' | 'review_required' | 'error'
  stage: DocumentIntelligenceStage | null
}
