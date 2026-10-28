// Synthetic UI data only. Never loaded by the application or sent to a live backend.
export const filename = 'Project delivery agreement.pdf'
export const user = {
  id: 'ui-test-user',
  name: 'Alex Morgan',
  email: 'alex@example.test',
  emailVerified: true,
  createdAt: '2026-01-01T00:00:00Z',
  updatedAt: '2026-01-01T00:00:00Z',
}
export const session = {
  user,
  session: {
    id: 'ui-test-session',
    token: 'fixture-only-not-a-live-session',
    userId: user.id,
    expiresAt: '2099-01-01T00:00:00Z',
    createdAt: user.createdAt,
    updatedAt: user.updatedAt,
  },
}
export const documentCase = {
  case_id: 'ui-fixture-case',
  status: 'needs_human_review',
  stage: 'finalized',
  document: {
    filename,
    page_count: 8,
    chunk_count: 24,
    method: 'pymupdf',
    source_file_available: true,
  },
  citations: [
    {
      id: 'C1',
      filename,
      page: 2,
      chunk_index: 1,
      excerpt:
        'The supplier shall deliver the first release by 15 October 2026. The delivery owner is the project manager. The agreed project budget is EUR 48,000.',
    },
    {
      id: 'C2',
      filename,
      page: 4,
      chunk_index: 2,
      excerpt:
        'Acceptance testing must be completed by 28 October 2026. The product owner must approve the acceptance report before release.',
    },
    {
      id: 'C3',
      filename,
      page: 6,
      chunk_index: 3,
      excerpt:
        'A delay beyond the agreed delivery date may trigger a contractual penalty. A revised schedule requires written approval from both parties.',
    },
  ],
  document_profile: {
    document_type: 'Service agreement',
    language: 'English',
    parties: ['Northline Studio', 'Acme Operations'],
    topics: [
      'Delivery milestones',
      'Acceptance criteria',
      'Supplier obligations',
    ],
    summary:
      'A delivery agreement covering release milestones, acceptance testing and supplier obligations. The next milestone is the first release, followed by the product owner’s acceptance review.',
    citation_ids: ['C1', 'C2'],
    quality: { extraction_quality: 'good', page_count: 8 },
  },
  facts: [
    {
      id: 'F1',
      statement: 'The agreed project budget is EUR 48,000.',
      category: 'commercial',
      confidence: 'high',
      citation_ids: ['C1'],
    },
    {
      id: 'F2',
      statement: 'Acceptance requires the product owner’s signed report.',
      category: 'approval',
      confidence: 'high',
      citation_ids: ['C2'],
    },
    {
      id: 'F3',
      statement: 'Schedule changes require approval from both parties.',
      category: 'governance',
      confidence: 'high',
      citation_ids: ['C3'],
    },
    {
      id: 'F4',
      statement: 'Late delivery may trigger a contractual penalty.',
      category: 'liability',
      confidence: 'high',
      citation_ids: ['C3'],
    },
    {
      id: 'F5',
      statement: 'The project manager owns the initial release milestone.',
      category: 'ownership',
      confidence: 'high',
      citation_ids: ['C1'],
    },
  ],
  obligations: [
    {
      id: 'O1',
      action: 'Deliver the first release',
      owner: 'Project manager',
      due_date: '2026-10-15',
      severity: 'high',
      consequence_if_missed: 'A contractual penalty may apply.',
      citation_ids: ['C1', 'C3'],
    },
    {
      id: 'O2',
      action: 'Approve the acceptance report',
      owner: 'Product owner',
      due_date: '2026-10-28',
      severity: 'medium',
      citation_ids: ['C2'],
    },
    {
      id: 'O3',
      action: 'Document approval for any schedule change',
      owner: 'Both parties',
      severity: 'medium',
      trigger: 'Schedule changes',
      citation_ids: ['C3'],
    },
  ],
  deadlines: [
    {
      id: 'D1',
      event: 'First release delivery',
      date: '2026-10-15',
      owner: 'Project manager',
      status: 'pending',
      citation_ids: ['C1'],
    },
    {
      id: 'D2',
      event: 'Acceptance report approval',
      date: '2026-10-28',
      owner: 'Product owner',
      status: 'pending',
      citation_ids: ['C2'],
    },
  ],
  overall_risk: 'high',
  risks: [
    {
      id: 'R1',
      title: 'Late delivery exposure',
      level: 'high',
      rationale:
        'Missing the delivery milestone may trigger a contractual penalty.',
      mitigation:
        'Confirm delivery readiness with the project manager before the milestone.',
      citation_ids: ['C3'],
    },
    {
      id: 'R2',
      title: 'Acceptance approval dependency',
      level: 'medium',
      rationale: 'Release depends on approval of the acceptance report.',
      mitigation:
        'Arrange the acceptance review and confirm the approver’s availability.',
      citation_ids: ['C2'],
    },
  ],
  audit: {
    passed: false,
    verification_available: true,
    reason: 'One recommendation needs a manual source check before approval.',
    summary: { supported: 12, unsupported: 1, unverifiable: 0 },
    sentences: [
      {
        text: 'The first release is due on 15 October 2026.',
        supported: true,
        citation_ids: ['C1'],
        reason: 'Explicit delivery date in the source.',
      },
      {
        text: 'Confirm delivery readiness before the milestone.',
        supported: false,
        citation_ids: ['C1', 'C3'],
        reason:
          'A proposed mitigation, not an explicit contractual requirement.',
      },
      {
        text: 'The product owner must approve the acceptance report.',
        supported: true,
        citation_ids: ['C2'],
      },
    ],
  },
  final_action_pack: {
    verification_status: 'needs_human_review',
    human_review_required: true,
    executive_summary:
      'Prioritise the release milestone, confirm acceptance ownership and inspect the contractual exposure before approving any change.',
    next_step:
      'Review the flagged recommendation against the original agreement.',
    decisions_required: [
      {
        id: 'DEC1',
        decision:
          'Confirm whether the release is ready for the agreed delivery date.',
        citation_ids: ['C1'],
      },
      {
        id: 'DEC2',
        decision: 'Approve or reject any proposed schedule change in writing.',
        citation_ids: ['C3'],
      },
    ],
    action_items: [
      {
        id: 'A1',
        title: 'Confirm first-release readiness',
        suggested_owner: 'Project manager',
        due_date: '2026-10-15',
        priority: 'high',
        approval_required: true,
        citation_ids: ['C1', 'C3'],
      },
      {
        id: 'A2',
        title: 'Schedule the acceptance review',
        suggested_owner: 'Product owner',
        due_date: '2026-10-28',
        priority: 'medium',
        citation_ids: ['C2'],
      },
      {
        id: 'A3',
        title: 'Record written approval of schedule changes',
        suggested_owner: 'Both parties',
        priority: 'medium',
        citation_ids: ['C3'],
      },
    ],
    open_questions: [
      'Has the project manager confirmed readiness?',
      'Has the acceptance reviewer been assigned?',
    ],
  },
}
