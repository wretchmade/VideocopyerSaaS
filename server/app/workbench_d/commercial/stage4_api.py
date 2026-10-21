"""One shared operation catalog for MCP, HTTP and the production workspace."""
SPECS={
 'prepare_studio':('Create a checksum-pinned review copy of one successful build','commandId buildId',''),
 'add_feedback':('Attach feedback to an exact review revision and frame','commandId reviewId frame body',''),
 'resolve_feedback':('Resolve a versioned review comment','commandId feedbackId baseVersion','note'),
 'reopen_feedback':('Reopen a versioned review comment','commandId feedbackId baseVersion','note'),
 'get_feedback':('Read review comments, exact binding and event history','reviewId',''),
 'sync_feedback':('Import uniquely identified offline comments into the same reviewed revision','commandId reviewId documentHash comments',''),
 'save_view':('Persist task groups, card layout and viewport for one exact revision','commandId projectId revision baseVersion view',''),
 'canvas_status':('Read a revision view and browser-visible receipts','projectId revision',''),
 'record_view':('Record an actual rendered/visible browser acknowledgement, not service readiness','commandId projectId revision documentHash viewVersion session visibility',''),
 'archive_workflow':('Archive a self-contained D project and licensed assets without budget or credentials','commandId projectId revision name','parameterDeclarations'),
 'list_workflows':('Search the rebuildable workflow index','','query'),
 'rebuild_index':('Rebuild workflow search metadata from integrity-checked archives','commandId',''),
 'preflight_reuse':('Check replacement inputs, missing assets and compatibility before reuse','workflowId','replacements bindings parameters'),
 'instantiate_workflow':('Create an independent project from explicit workflow inputs; no inherited budget','commandId workflowId name','replacements bindings parameters'),
 'retention_check':('Report retained revision/build/review/workflow references without deleting files','sha256',''),
 'choose_export':('Record a user export choice bound to one immutable delivery','commandId deliveryId format allowBaked',''),
 'export_draft':('Create a managed editable draft from a delivery-bound export choice','commandId choiceId name',''),
 'jianying_create':('Create an independent managed draft from an exact D project revision','commandId projectId revision name allowBaked',''),
 'jianying_import':('Read a supported plaintext draft without modifying its source; reject encrypted or locked input','commandId directory expectedHash name','assetLicenses'),
 'jianying_list':('List managed draft identities and current immutable revisions','',''),
 'jianying_inspect':('Inspect native tracks, media hashes and manual changes','draftId','revision'),
 'jianying_edit':('Trim, split, move, change volume/text or delete using immutable draft revisions','commandId draftId baseRevision expectedHash actions',''),
 'jianying_publish':('Install an exact draft revision into a NEW explicit directory; never overwrite','commandId draftId revision expectedHash directory',''),
}

def tools():
    integer={'revision','frame','baseVersion','viewVersion','baseRevision'};objects={'view','parameters','replacements','assetLicenses'};arrays={'comments','parameterDeclarations','bindings','actions'}
    rows=[]
    for name,(description,required,optional) in SPECS.items():
        props={k:{'type':'integer','minimum':0} if k in integer else {'type':'boolean'} if k=='allowBaked' else {'type':'object'} if k in objects else {'type':'array','items':{'type':'object'}} if k in arrays else {'type':'string'} for k in (required+' '+optional).split()}
        rows.append(dict(name='d_'+name,description=description,inputSchema=dict(type='object',properties=props,required=required.split(),additionalProperties=False)))
    return rows

def dispatch(engine,name,args):
    if name.startswith('jianying_') or name in ('choose_export','export_draft'):
        from .drafts import Drafts
        drafts=Drafts(engine);method=getattr(drafts,'import_draft' if name=='jianying_import' else name.removeprefix('jianying_'));return method(args)
    from .production_state import ProductionState
    state=ProductionState(engine)
    if name in ('resolve_feedback','reopen_feedback'):return state.feedback_state(args,'resolved' if name=='resolve_feedback' else 'open')
    return getattr(state,name)(args)
