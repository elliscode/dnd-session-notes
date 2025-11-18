  {
    let div = document.createElement('div');
    div.classList.add('card');
    div.classList.add('auto');
    div.classList.add('medium');
    div.classList.add('column')
    let label = document.createElement('label');

    let span = document.createElement('span');
    span.innerText = "Campaign: ";
    label.appendChild(span);

    let select = document.createElement('select');
    let option = document.createElement('option');
    option.innerText = 'Eberron';
    option.value = option.innerText;
    select.appendChild(option);

    label.appendChild(select);
    div.appendChild(label);
    content.appendChild(div);
  }

  {
    let div = document.createElement('div');
    div.classList.add('card');
    div.classList.add('auto');
    div.classList.add('medium');
    div.classList.add('row');

    {
      let button = document.createElement('button');
      button.innerText = 'All';
      button.classList.add('selected');
      div.appendChild(button);
    }
    {
      let button = document.createElement('button');
      button.innerText = 'Characters';
      div.appendChild(button);
    }
    {
      let button = document.createElement('button');
      button.innerText = 'Sessions';
      div.appendChild(button);
    }
    {
      let button = document.createElement('button');
      button.innerText = 'Places';
      div.appendChild(button);
    }
    content.appendChild(div);
  }

  for (let entry of json) {
    let div = document.createElement('div');
    div.classList.add('card');
    div.classList.add('column');
    div.classList.add('large');
    div.innerHTML = marked.parse(entry.markdown);
    content.appendChild(div);
  }