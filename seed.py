from datetime import timedelta
from app import app, db, Challenge, Question, utcnow

QUESTIONS = [
    ("Which AWS service provides scalable object storage?",
     ["Amazon EBS", "Amazon S3", "Amazon RDS", "AWS Lambda"], "b"),
    ("What is AWS IAM used for?",
     ["Managing users and permissions", "Monitoring costs", "Storing files", "Routing DNS"], "a"),
    ("Which service lets you run code without managing servers?",
     ["Amazon RDS", "Amazon S3", "AWS Lambda", "Amazon VPC"], "c"),
    ("In the shared responsibility model, who secures the physical data centres and hardware?",
     ["The customer", "Your internet provider", "A third-party auditor", "AWS"], "d"),
    ("Which EC2 purchasing option suits interruptible workloads and offers up to 90% off On-Demand prices?",
     ["On-Demand", "Spot Instances", "Dedicated Hosts", "Savings Plans"], "b"),
]

with app.app_context():
    for old in Challenge.query.all():
        old.is_active = False

    challenge = Challenge(
        title="AWS Cloud Blitz",
        description="Answer 5 AWS questions as fast as you can. Speed earns bonus points.",
        ends_at=utcnow() + timedelta(hours=24),
    )
    db.session.add(challenge)
    db.session.flush()

    for text, opts, correct in QUESTIONS:
        db.session.add(Question(
            challenge_id=challenge.id, text=text,
            option_a=opts[0], option_b=opts[1], option_c=opts[2], option_d=opts[3],
            correct=correct))
    db.session.commit()
    print("Seeded challenge with", len(QUESTIONS), "questions.")