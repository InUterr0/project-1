from kivy.app import App
from kivy.uix.screenmanager import ScreenManager, Screen
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.textinput import TextInput
from kivy.uix.spinner import Spinner
from kivy.uix.scrollview import ScrollView
from kivy.uix.gridlayout import GridLayout
from kivy.uix.popup import Popup
from kivy.uix.camera import Camera
from kivy.clock import Clock
from datetime import datetime
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Image
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER
import firebase_admin
from firebase_admin import credentials
from firebase_admin import firestore
from firebase_admin import storage
import tempfile
import os
from google.colab import files

# Upload the serviceAccountKey.json file
uploaded = files.upload()
with open('serviceAccountKey.json', 'wb') as f:
    f.write(uploaded['serviceAccountKey.json'])

# Initialize Firebase
cred = credentials.Certificate("serviceAccountKey.json")
firebase_admin.initialize_app(cred, {'storageBucket': 'your-storage-bucket-name.appspot.com'})
db = firestore.client()
bucket = storage.bucket()

class Project:
    def __init__(self, name, budget_robocizna=0, budget_material=0):
        self.name = name
        self.budget_robocizna = budget_robocizna
        self.budget_material = budget_material
        self.koszty = []
        self.archived = False

class ProjectSelectionScreen(Screen):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.layout = BoxLayout(orientation='vertical', spacing=10, padding=10)
        self.project_spinner = Spinner(text='Välj projekt', values=self.get_project_list())
        self.layout.add_widget(self.project_spinner)
        self.layout.add_widget(Button(text='Nytt projekt', on_press=self.new_project))
        self.layout.add_widget(Button(text='Öppna projekt', on_press=self.open_project))
        self.layout.add_widget(Button(text='Arkivera/Återställ', on_press=self.toggle_archive))
        self.add_widget(self.layout)

    def get_project_list(self):
        app = App.get_running_app()
        active_projects = [name for name, project in app.projects.items() if not project.archived]
        archived_projects = [name for name, project in app.projects.items() if project.archived]
        return active_projects + ["--- Arkiverade projekt ---"] + archived_projects

    def new_project(self, instance):
        content = BoxLayout(orientation='vertical')
        self.project_name_input = TextInput(multiline=False)
        content.add_widget(Label(text='Ange projektnamn:'))
        content.add_widget(self.project_name_input)
        
        popup = Popup(title='Nytt projekt', content=content, size_hint=(None, None), size=(300, 200))
        
        def on_submit(instance):
            name = self.project_name_input.text
            if name and name not in App.get_running_app().projects:
                App.get_running_app().projects[name] = Project(name)
                self.project_spinner.values = self.get_project_list()
                self.project_spinner.text = name
                App.get_running_app().save_project_to_firebase(App.get_running_app().projects[name])
                popup.dismiss()
            else:
                error_label = Label(text='Ogiltigt namn eller projektet finns redan')
                content.add_widget(error_label)
                Clock.schedule_once(lambda dt: content.remove_widget(error_label), 2)
        
        submit_button = Button(text='Skapa', on_press=on_submit)
        content.add_widget(submit_button)
        
        popup.open()

    def open_project(self, instance):
        if self.project_spinner.text in App.get_running_app().projects:
            App.get_running_app().current_project = App.get_running_app().projects[self.project_spinner.text]
            self.manager.current = 'add_costs'

    def toggle_archive(self, instance):
        if self.project_spinner.text in App.get_running_app().projects:
            project = App.get_running_app().projects[self.project_spinner.text]
            project.archived = not project.archived
            App.get_running_app().save_project_to_firebase(project)
            self.project_spinner.values = self.get_project_list()
            popup = Popup(title='Information', content=Label(text=f"Projekt {'arkiverat' if project.archived else 'återställt'}"), size_hint=(None, None), size=(300, 200))
            popup.open()

class AddCostsScreen(Screen):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.layout = BoxLayout(orientation='vertical', spacing=10, padding=10)
        self.layout.add_widget(Label(text='Lägg till kostnad'))
        self.typ_spinner = Spinner(text='Typ', values=('arbetskraft', 'material', 'materialåterbetalning'))
        self.layout.add_widget(self.typ_spinner)
        self.amount_input = TextInput(hint_text='Belopp')
        self.layout.add_widget(self.amount_input)
        self.name_input = TextInput(hint_text='Namn')
        self.layout.add_widget(self.name_input)
        self.date_input = TextInput(text=datetime.now().strftime("%Y-%m-%d"), hint_text='Datum')
        self.layout.add_widget(self.date_input)
        self.layout.add_widget(Button(text='Ta en bild', on_press=self.take_photo))
        self.layout.add_widget(Button(text='Lägg till', on_press=self.add_cost))
        self.summary_label = Label(text='Sammanfattning')
        self.layout.add_widget(self.summary_label)
        self.layout.add_widget(Button(text='Detaljerad sammanfattning', on_press=self.show_detailed_summary))
        self.layout.add_widget(Button(text='Visa kostnader', on_press=self.show_costs))
        self.layout.add_widget(Button(text='Tillbaka till projektval', on_press=self.go_back_to_projects))
        self.add_widget(self.layout)
        self.current_photo = None

    def take_photo(self, instance):
        # W środowisku Colab nie mamy dostępu do kamery, więc możemy zamiast tego pozwolić na upload pliku
        uploaded = files.upload()
        if uploaded:
            filename = list(uploaded.keys())[0]
            self.current_photo = filename

    def add_cost(self, instance):
        app = App.get_running_app()
        if not app.current_project:
            popup = Popup(title='Fel', content=Label(text='Inget projekt valt.'), size_hint=(None, None), size=(300, 200))
            popup.open()
            return

        typ = self.typ_spinner.text
        kwota = float(self.amount_input.text or 0)
        data = self.date_input.text

        photo_url = None
        if self.current_photo:
            blob = bucket.blob(f"{app.current_project.name}/{os.path.basename(self.current_photo)}")
            blob.upload_from_filename(self.current_photo)
            photo_url = blob.public_url

        if typ == "arbetskraft":
            koszt = {
                "typ": typ,
                "godziny": kwota,
                "kwota": kwota * app.STAWKA_GODZINOWA,
                "data": data,
                "vat_included": False,
                "photo_url": photo_url
            }
        elif typ in ["material", "materialåterbetalning"]:
            nazwa = self.name_input.text
            koszt = {
                "typ": typ,
                "kwota": kwota if typ == "material" else -kwota,
                "nazwa": nazwa,
                "data": data,
                "vat_included": False,
                "photo_url": photo_url
            }

        app.current_project.koszty.append(koszt)
        app.save_project_to_firebase(app.current_project)
        self.update_summary()
        self.current_photo = None

    def update_summary(self):
        app = App.get_running_app()
        if not app.current_project:
            self.summary_label.text = "Inget projekt valt"
            return

        robocizna = sum(k["godziny"] * app.STAWKA_GODZINOWA for k in app.current_project.koszty if k["typ"] == "arbetskraft")
        material = sum(k["kwota"] for k in app.current_project.koszty if k["typ"] in ["material", "materialåterbetalning"])
        total = robocizna + material
        
        budget_total = app.current_project.budget_robocizna + app.current_project.budget_material
        procent_total = (total / budget_total) * 100 if budget_total else 0

        summary = f"Totalt: {total:.2f} SEK\n"
        summary += f"Budgetanvändning: {procent_total:.2f}%"

        self.summary_label.text = summary

    def show_detailed_summary(self, instance):
        self.manager.current = 'detailed_summary'

    def show_costs(self, instance):
        self.manager.current = 'cost_list'

    def go_back_to_projects(self, instance):
        self.manager.current = 'project_selection'

class DetailedSummaryScreen(Screen):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.layout = BoxLayout(orientation='vertical', spacing=10, padding=10)
        self.summary_label = Label(text='')
        self.layout.add_widget(self.summary_label)
        self.layout.add_widget(Button(text='Generera PDF-rapport', on_press=self.generate_pdf_report))
        self.layout.add_widget(Button(text='Tillbaka', on_press=self.go_back))
        self.add_widget(self.layout)

    def on_enter(self):
        self.update_summary()

    def update_summary(self):
        app = App.get_running_app()
        if not app.current_project:
            self.summary_label.text = "Inget projekt valt"
            return

        robocizna = sum(k["godziny"] * app.STAWKA_GODZINOWA for k in app.current_project.koszty if k["typ"] == "arbetskraft")
        material = sum(k["kwota"] for k in app.current_project.koszty if k["typ"] in ["material", "materialåterbetalning"])
        total = robocizna + material
        
        robocizna_vat = robocizna * (1 + app.VAT_RATE)
        robocizna_vat_rot = robocizna_vat * (1 - app.ROT_RATE)
        material_vat = material * (1 + app.VAT_RATE)

        total_med_moms_minus_rot = robocizna_vat_rot + material_vat
        total_med_moms = robocizna_vat + material_vat
        total_utan_moms = robocizna + material

        budget_total = app.current_project.budget_robocizna + app.current_project.budget_material
        procent_robocizna = (robocizna / app.current_project.budget_robocizna) * 100 if app.current_project.budget_robocizna else 0
        procent_material = (material / app.current_project.budget_material) * 100 if app.current_project.budget_material else 0
        procent_total = (total / budget_total) * 100 if budget_total else 0

        summary = f"Sammanfattning:\n\n"
        summary += f"Totalt (med moms, minus ROT): {total_med_moms_minus_rot:.2f} SEK\n"
        summary += f"Totalt (med moms): {total_med_moms:.2f} SEK\n"
        summary += f"Totalt (utan moms): {total_utan_moms:.2f} SEK\n\n"
        summary += f"Arbetskraft: {robocizna:.2f} SEK ({procent_robocizna:.2f}% av budget)\n"
        summary += f"Material: {material:.2f} SEK ({procent_material:.2f}% av budget)\n"
        summary += f"Totalt: {total:.2f} SEK ({procent_total:.2f}% av total budget)"

        self.summary_label.text = summary

    def generate_pdf_report(self, instance):
        app = App.get_running_app()
        app.generate_pdf_report()

    def go_back(self, instance):
        self.manager.current = 'add_costs'

class CostListScreen(Screen):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.layout = BoxLayout(orientation='vertical', spacing=10, padding=10)
        self.cost_list = GridLayout(cols=4, size_hint_y=None)
        self.cost_list.bind(minimum_height=self.cost_list.setter('height'))
        scroll = ScrollView(size_hint=(1, None), size=(400, 400))
        scroll.add_widget(self.cost_list)
        self.layout.add_widget(scroll)
        self.layout.add_widget(Button(text='Tillbaka', on_press=self.go_back))
        self.add_widget(self.layout)

    def on_enter(self):
        self.refresh_cost_list()

    def refresh_cost_list(self):
        app = App.get_running_app()
        self.cost_list.clear_widgets()
        if app.current_project:
            for koszt in app.current_project.koszty:
                self.cost_list.add_widget(Label(text=koszt['typ']))
                self.cost_list.add_widget(Label(text=f"{koszt['kwota']:.2f}"))
                self.cost_list.add_widget(Label(text=koszt['data']))
                if koszt.get('photo_url'):
                    self.cost_list.add_widget(Button(text='Visa bild', on_press=lambda x, url=koszt['photo_url']: self.show_image(url)))
                else:
                    self.cost_list.add_widget(Label(text='Ingen bild'))

    def show_image(self, url):
        # Tutaj możesz dodać kod do wyświetlania obrazu w popupie
        pass

    def go_back(self, instance):
        self.manager.current = 'add_costs'

class BudgetCalculatorApp(App):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.projects = {}
        self.current_project = None
        self.STAWKA_GODZINOWA = 600  # SEK/h
        self.VAT_RATE = 0.25  # 25% VAT
        self.ROT_RATE = 0.30  # 30% ROT deduction

    def build(self):
        self.load_projects_from_firebase()
        sm = ScreenManager()
        sm.add_widget(ProjectSelectionScreen(name='project_selection'))
        sm.add_widget(AddCostsScreen(name='add_costs'))
        sm.add_widget(DetailedSummaryScreen(name='detailed_summary'))
        sm.add_widget(CostListScreen(name='cost_list'))
        return sm

    def save_project_to_firebase(self, project):
        if project:
            doc_ref = db.collection('projects').document(project.name)
            doc_ref.set({
                'name': project.name,
                'budget_robocizna': project.budget_robocizna,
                'budget_material': project.budget_material,
                'koszty': project.koszty,
                'archived': project.archived
            })

    def load_projects_from_firebase(self):
        projects_ref = db.collection('projects')
        docs = projects_ref.get()
        for doc in docs:
            data = doc.to_dict()
            project = Project(data['name'], data['budget_robocizna'], data['budget_material'])
            project.koszty = data['koszty']
            project.archived = data['archived']
            self.projects[data['name']] = project

    def generate_pdf_report(self):
        if not self.current_project:
            popup = Popup(title='Fel', content=Label(text='Välj ett projekt först.'), size_hint=(None, None), size=(300, 200))
            popup.open()
            return

        doc = SimpleDocTemplate(f"{self.current_project.name}_rapport.pdf", pagesize=letter)
        elements = []

        styles = getSampleStyleSheet()
        styles.add(ParagraphStyle(name='Center', alignment=TA_CENTER))
        styles.add(ParagraphStyle(name='Bold', fontName='Helvetica-Bold', fontSize=12))
        styles.add(ParagraphStyle(name='Small', fontName='Helvetica', fontSize=8))

        elements.append(Paragraph(f"Projektrapport: {self.current_project.name}", styles['Title']))

        # Budget information
        budget_data = [
            ["Budget arbetskraft", f"{self.current_project.budget_robocizna:.2f} SEK"],
            ["Budget material", f"{self.current_project.budget_material:.2f} SEK"],
            ["Timkostnad", f"{self.STAWKA_GODZINOWA:.2f} SEK/h"]
        ]
        budget_table = Table(budget_data)
        budget_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 14),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
            ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
            ('TEXTCOLOR', (0, 1), (-1, -1), colors.black),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
            ('FONTSIZE', (0, 1), (-1, -1), 12),
            ('TOPPADDING', (0, 1), (-1, -1), 6),
            ('BOTTOMPADDING', (0, 1), (-1, -1), 6),
            ('GRID', (0, 0), (-1, -1), 1, colors.black)
        ]))
        elements.append(budget_table)

        # Costs table
        cost_data = [["Typ", "Belopp", "Datum", "Detaljer", "Bild"]]
        for cost in self.current_project.koszty:
            if cost['typ'] == 'arbetskraft':
                details = f"{cost['godziny']} timmar"
            else:
                details = cost['nazwa']
            
            image = None
            if cost.get('photo_url'):
                # Pobierz obraz z Firebase Storage i zapisz tymczasowo
                blob = bucket.blob(cost['photo_url'])
                _, temp_local_filename = tempfile.mkstemp()
                blob.download_to_filename(temp_local_filename)
                image = Image(temp_local_filename, width=100, height=100)
            
            cost_data.append([cost['typ'], f"{cost['kwota']:.2f}", cost['data'], details, image if image else ''])

        cost_table = Table(cost_data)
        cost_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 14),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
            ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
            ('TEXTCOLOR', (0, 1), (-1, -1), colors.black),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
            ('FONTSIZE', (0, 1), (-1, -1), 12),
            ('TOPPADDING', (0, 1), (-1, -1), 6),
            ('BOTTOMPADDING', (0, 1), (-1, -1), 6),
            ('GRID', (0, 0), (-1, -1), 1, colors.black)
        ]))
        elements.append(cost_table)

        # Summary
        robocizna = sum(k["godziny"] * self.STAWKA_GODZINOWA for k in self.current_project.koszty if k["typ"] == "arbetskraft")
        material = sum(k["kwota"] for k in self.current_project.koszty if k["typ"] in ["material", "materialåterbetalning"])
        
        robocizna_vat = robocizna * (1 + self.VAT_RATE)
        robocizna_vat_rot = robocizna_vat * (1 - self.ROT_RATE)
        material_vat = material * (1 + self.VAT_RATE)

        total_med_moms_minus_rot = robocizna_vat_rot + material_vat
        total_med_moms = robocizna_vat + material_vat
        total_utan_moms = robocizna + material

        budget_total = self.current_project.budget_robocizna + self.current_project.budget_material
        procent_robocizna = (robocizna / self.current_project.budget_robocizna) * 100 if self.current_project.budget_robocizna else 0
        procent_material = (material / self.current_project.budget_material) * 100 if self.current_project.budget_material else 0
        procent_total = (total_utan_moms / budget_total) * 100 if budget_total else 0

        elements.append(Paragraph("Sammanfattning", styles['Heading2']))
        elements.append(Paragraph(f"Totalt (med moms, minus ROT): {total_med_moms_minus_rot:.2f} SEK", styles['Bold']))
        elements.append(Paragraph(f"Totalt (med moms): {total_med_moms:.2f} SEK", styles['Normal']))
        elements.append(Paragraph(f"Totalt (utan moms): {total_utan_moms:.2f} SEK", styles['Normal']))

        elements.append(Paragraph("Budgetanvändning", styles['Heading3']))
        elements.append(Paragraph(f"Arbetskraft: {robocizna:.2f} SEK ({procent_robocizna:.2f}% av budget)", styles['Normal']))
        elements.append(Paragraph(f"Material: {material:.2f} SEK ({procent_material:.2f}% av budget)", styles['Normal']))
        elements.append(Paragraph(f"Totalt: {total_utan_moms:.2f} SEK ({procent_total:.2f}% av total budget)", styles['Normal']))

        if procent_total > 100:
            elements.append(Paragraph(f"Varning: Kostnaden överstiger budgeten med {procent_total - 100:.2f}%!", styles['Bold']))

        doc.build(elements)

        # W Colab używamy files.download zamiast Popup
        files.download(f"{self.current_project.name}_rapport.pdf")

if __name__ == '__main__':
    BudgetCalculatorApp().run()