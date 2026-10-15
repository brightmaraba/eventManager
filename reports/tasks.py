from celery import shared_task


@shared_task(name="reports.render_pdf")
def render_pdf(job_id):
    from reports.services import render_job

    render_job(job_id)
