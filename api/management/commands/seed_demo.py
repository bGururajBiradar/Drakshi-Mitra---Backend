from django.core.management.base import BaseCommand
from api.models import User,GrapeVariety,GrowthStageRule,ExpenseCategory

class Command(BaseCommand):
    help="Seed Drakshi Mitra master data and an optional demo farmer."
    def add_arguments(self,parser):
        parser.add_argument("--demo",action="store_true")
    def handle(self,*args,**opts):
        for name in ["Thompson Seedless","Manik Chaman","Super Sonaka"]:
            GrapeVariety.objects.get_or_create(name=name)
        stages=[
            ("Budburst",1,0,20),("Flower cluster initiation",2,21,45),("Flowering",3,46,70),
            ("Fruit set",4,71,100),("Berry development",5,101,180),("Harvest",6,181,220),("Dormancy",7,221,365)
        ]
        for name,order,start,end in stages: GrowthStageRule.objects.update_or_create(order=order,defaults={"name":name,"start_day":start,"end_day":end,"is_active":True})
        if opts["demo"]:
            u,_=User.objects.get_or_create(phone="9876543210",defaults={"name":"Demo Farmer","role":User.Role.FARMER})
            u.set_password("123456"); u.save()
            for c in ["Farm operations","Fertilizer","Sprays","Fuel","Labour","Other"]: ExpenseCategory.objects.get_or_create(owner=u,name=c)
        self.stdout.write(self.style.SUCCESS("Drakshi Mitra master data seeded."))
