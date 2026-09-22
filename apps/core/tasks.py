from celery import shared_task
from .services import execute_job
@shared_task(acks_late=True,reject_on_worker_lost=True)
def process_job(job_id):
    return str(execute_job(job_id).id)
