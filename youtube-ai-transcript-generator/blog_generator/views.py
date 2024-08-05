
import time
from django.contrib.auth.models import User
from django.contrib.auth import authenticate, login, logout
from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.views.decorators.csrf import csrf_exempt
from django.http import JsonResponse
from django.conf import settings
import json
import yt_dlp
import os
import assemblyai as aai
from transformers import pipeline, set_seed
import httpx
from .models import BlogPost

# Create your views here.
@login_required
def index(request):
    return render(request, 'index.html')

@csrf_exempt
def generate_blog(request):
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            yt_link = data['link']
        except (KeyError, json.JSONDecodeError):
            return JsonResponse({'error': 'Invalid data sent'}, status=400)

        # get yt title
        title = yt_title(yt_link)

        # get transcript
        transcription = get_transcription(yt_link)

        if not transcription:
            return JsonResponse({'error': "Failed to get transcript"}, status=500)

        blog_content = generate_blog_from_transcription(transcription)
        if not blog_content:
            return JsonResponse({'error': "Failed to generate blog article"}, status=500)

        # save blog article to database
        new_blog_article = BlogPost.objects.create(
            user=request.user,
            youtube_title=title,
            youtube_link=yt_link,
            generated_content=blog_content,
        )
        new_blog_article.save()

        # return blog article as a response
        return JsonResponse({'content': blog_content})
    else:
        return JsonResponse({'error': 'Invalid request method'}, status=405)

def yt_title(link):
    ydl_opts = {
        'quiet': True,
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info_dict = ydl.extract_info(link, download=False)
        return info_dict.get('title', 'No title found')

def download_audio(link):
    ydl_opts = {
        'format': 'bestaudio/best',
        'outtmpl': os.path.join(settings.MEDIA_ROOT, '%(title)s.%(ext)s'),
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '192',
        }],
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info_dict = ydl.extract_info(link, download=True)
        audio_file = ydl.prepare_filename(info_dict)
        base, ext = os.path.splitext(audio_file)
        new_file = base + '.mp3'
        if os.path.exists(new_file):
            return new_file
        else:
            raise Exception("Failed to download audio")

# FUNCTION FOR EFFECTIVE TEXT GENERATION USING GPT-3.5-TURBO JUST ADD THE KEY AND ADD THE PROMPT FOR IT
# def get_transcription(link):
#     audio_file = download_audio(link)
#     aai.settings.api_key = "YOUR API KEY"

#     transcriber = aai.Transcriber()
#     transcript = transcriber.transcribe(audio_file)

#     return transcript.text

def get_transcription(link):
    audio_file = download_audio(link)
    aai.settings.api_key = "YOUR ASSEMBLY AI KEY"

    transcriber = aai.Transcriber()
    retries = 3
    for i in range(retries):
        try:
            transcript = transcriber.transcribe(audio_file)
            return transcript.text
        except httpx.ReadTimeout:
            if i < retries - 1:
                time.sleep(2)  # wait before retrying
                continue
            else:
                raise
    return None


def generate_blog_from_transcription(transcription):
    generator = pipeline('text-generation', model='gpt2-medium')
    set_seed(42)

    prompt = f"Enhance this content: {transcription}\n\n"
    generated = generator(prompt, max_length=1000, num_return_sequences=1)
    blog_content = generated[0]['generated_text']
    
    return blog_content


def blog_list(request):
    blog_articles = BlogPost.objects.filter(user=request.user)
    return render(request, "all-blogs.html", {'blog_articles': blog_articles})

def blog_details(request, pk):
    blog_article_detail = BlogPost.objects.get(id=pk)
    if request.user == blog_article_detail.user:
        return render(request, 'blog-details.html', {'blog_article_detail': blog_article_detail})
    else:
        return redirect('/')
    
def user_login(request):
    if request.method == 'POST':
        username = request.POST['username']
        password = request.POST['password']

        user = authenticate(request, username=username, password=password)
        if user is not None:
            login(request, user)
            return redirect('/')
        else:
            error_message = "Invalid username or password"
            return render(request, 'login.html', {'error_message': error_message})
        
    return render(request, 'login.html')

def user_signup(request):
    if request.method == 'POST':
        username = request.POST['username']
        email = request.POST['email']
        password = request.POST['password']
        repeatPassword = request.POST['repeatPassword']

        if password == repeatPassword:
            try:
                user = User.objects.create_user(username, email, password)
                user.save()
                login(request, user)
                return redirect('/')
            except:
                error_message = 'Error creating account'
                return render(request, 'signup.html', {'error_message':error_message})
        else:
            error_message = 'Password do not match'
            return render(request, 'signup.html', {'error_message':error_message})
        
    return render(request, 'signup.html')

def user_logout(request):
    logout(request)
    return redirect('/')
