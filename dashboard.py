"""Local Streamlit interface. Run with uv run streamlit run dashboard.py."""
import json
import os
import streamlit as st
from dotenv import load_dotenv
from audit_client import request_json, get_job, RELATIONSHIPS, PLACEMENTS, FORMATS

load_dotenv()
st.set_page_config(page_title='Brand Guardian', layout='wide')
st.title('Brand Guardian')
st.caption('Evidence-grounded video compliance screening • Human review required for regulatory clearance')
key = st.sidebar.text_input('API key', value=os.getenv('API_KEY', ''), type='password')
with st.form('audit'):
    url = st.text_input('YouTube video URL')
    relationship = st.selectbox('Verified commercial relationship', RELATIONSHIPS)
    placement = st.selectbox('Verified YouTube placement', PLACEMENTS)
    ad_format = st.selectbox('Ad format', FORMATS)
    jurisdiction = st.text_input('Jurisdiction', 'UNKNOWN')
    submit = st.form_submit_button('Submit audit')
if submit:
    try:
        accepted = request_json('/audit/jobs', {'video_url': url, 'commercial_relationship': relationship,
            'youtube_placement': placement, 'ad_format': ad_format, 'jurisdiction': jurisdiction}, api_key=key)
        st.session_state['job_id'] = accepted['job_id']
        st.session_state['lookup'] = accepted['job_id']
        st.session_state.pop('job', None)
    except Exception as exc:
        st.error(str(exc))
if 'lookup' not in st.session_state:
    st.session_state['lookup'] = ''
job_id = st.text_input('Job ID (refresh or resume)', key='lookup')
auto_refresh = st.checkbox('Automatically refresh running jobs', value=True)

@st.fragment(run_every=5 if auto_refresh else None)
def show_job():
    refresh = st.button('Refresh status')
    if job_id and (refresh or auto_refresh or submit):
        previous = st.session_state.get('job') or {}
        if refresh or previous.get('job_id') != job_id or previous.get('status') not in {'COMPLETED','FAILED'}:
            try:
                st.session_state['job'] = get_job(job_id, api_key=key)
            except Exception as exc:
                st.error(str(exc))
    job = st.session_state.get('job')
    if job and job.get('job_id') != job_id:
        job = None
    if job:
        st.write('Job:', job['job_id'])
        st.metric('Execution', job['status'])
        st.write('Stage:', job.get('current_stage') or 'Pending')
        if job.get('error'):
            st.error(job['error'])
        result = job.get('result')
        if result:
            a,b,c = st.columns(3)
            a.metric('Final decision', result['final_status'])
            b.metric('Screening result', result.get('screening_status', 'Unknown'))
            c.metric('Requirements identified', len(result.get('requirement_assessments', [])))
            st.write(result.get('final_report'))
            st.caption(f"Extraction cache: {result.get('extraction_cache_status', 'UNKNOWN')} | Elapsed: {result.get('elapsed_seconds', 'Unknown')} seconds")
            for field in result.get('required_user_inputs', []):
                st.warning(f'Confirm {field} before rerunning.')
            for label, field in [('Policy applicability','policy_assessments'), ('Requirement findings','requirement_assessments'), ('Citations','citations'), ('Extraction status','extraction_status'), ('Grounding diagnostics','audit_diagnostics'), ('Stage timings','stage_events')]:
                with st.expander(label, expanded=field == 'policy_assessments'):
                    st.json(result.get(field))
            st.download_button('Download audit JSON', json.dumps(job, indent=2), file_name='audit_result.json', mime='application/json')

show_job()
